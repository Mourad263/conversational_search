"""Sprint 6 semantic benchmark v2 -- rebuilt so that NO expected label is
produced by the production resolvers. Evaluation artifact only; never
imported by production code.

Why v2 exists
-------------
v1 (sprint6_semantic_benchmark_build.py) computed each case's
expected_grounding by CALLING resolve_category_hint()/resolve_brand_text()/
resolve_free_from() on the hand-authored roles. That makes the evaluation
circular: the "expected" answer was by construction whatever the current
resolver already does, so a resolver-level error could never show up as a
miss. v1 also had five labels hand-changed AFTER seeing pipeline output.
Both are fixed here.

How labels are established in v2
--------------------------------
1. SEMANTIC ROLES are authored from the INTENDED USER MEANING of the
   sentence alone. For a typo case, raw_query_text keeps the user's
   misspelling (that is what was said) while category_hint carries the
   concept the user plainly meant. No role text was chosen by looking at
   model output.

2. CANONICAL GROUNDING is hand-written as a slug and then VERIFIED here
   against authoritative database evidence: canonical_category joined to
   category (the same existence condition production uses to expose a
   category at all) and canonical_brand joined to product.brand_normalized,
   with real product counts. The builder aborts if any referenced slug is
   absent or backs zero real products. Verification reads the catalog; it
   never calls a resolver, and the slug itself is chosen by NAME
   DENOTATION, i.e. the canonical row's own display_name_en/display_name_ar
   names the same concept the user asked for.

3. GROUNDING MODES make the "is this exactly recallable" question explicit
   instead of hiding it inside a None:
     exact          - exactly one canonical row DENOTES the request
                      ("milk" -> Milk, "عصير" -> العصائر). Counted in exact
                      category recall.
     ambiguous      - two or more canonical rows plausibly denote it
                      ("مكسرات" -> both `nuts` and Nuts & Seeds; shampoo ->
                      Hair Care or Shower/Bath/Soap). EXCLUDED from exact
                      category recall by rule.
     retrieval_only - the taxonomy has no row denoting the concept at all
                      ("peas", "corn", "tomato paste"); the request is
                      legitimately served by free-text retrieval, so no
                      exact category is asserted. Excluded from exact
                      recall.
     none           - the turn carries no product/brand expectation at all
                      (price-only, off-topic, remove_filter).

   acceptable_categories/acceptable_brands list every grounding that is
   NOT an error even when it is not the exact answer (a parent category,
   say). forbidden_categories/forbidden_brands name groundings that WOULD
   be a false hijack -- authored from catalog evidence that the row
   denotes something else entirely (e.g. `pears` is a real brand of 2
   products; it is not the vegetable "peas").

4. No label was chosen, widened or narrowed because the current pipeline
   returns something different. Where v1 had been relaxed to match
   observed output (peas, corn, رمان, عصار, ليمون, زبادي...), v2 states the
   meaning-true label instead, and several of those are expected to FAIL
   against today's pipeline. That is the point.

Usage: python evaluation/sprint6_semantic_benchmark_v2_build.py
Writes: sprint6_semantic_benchmark_v2_dev.json
        sprint6_semantic_benchmark_v2_holdout.json  (FROZEN)
        sprint6_semantic_benchmark_v2_holdout.sha256.txt
        sprint6_semantic_benchmark_v2_regression.json
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psycopg  # noqa: E402

from src.models.config import settings  # noqa: E402

SEED = 20260928
DEV_FRACTION = 0.70

SEARCH, ADD, MOD, REM, OFF = "search", "add_filter", "modify_filter", "remove_filter", "off_topic"
EXACT, AMBIG, RETRIEVAL, NONE = "exact", "ambiguous", "retrieval_only", "none"


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def case(tag, lang, sentence, *, history=None, intent=SEARCH, price_min=None, price_max=None,
         target_facet=None, raw=None, cat_hint=None, brand=None, free_from=None,
         mode=NONE, category=None, expected_brand=None, acceptable_categories=(),
         acceptable_brands=(), forbidden_categories=(), forbidden_brands=(), note="") -> dict:
    return {
        "tag": tag, "language": lang, "sentence": sentence, "history": history,
        "expected_action": {
            "intent": intent, "price_min": price_min, "price_max": price_max,
            "target_facet": target_facet,
        },
        "expected_roles": {
            "raw_query_text": raw, "category_hint": cat_hint,
            "brand_text": brand, "free_from": free_from,
        },
        "expected_grounding": {
            "mode": mode,
            "category": category,
            "brand": expected_brand,
            "acceptable_categories": list(acceptable_categories),
            "acceptable_brands": list(acceptable_brands),
            "forbidden_categories": list(forbidden_categories),
            "forbidden_brands": list(forbidden_brands),
        },
        "label_note": note,
    }


# ---------------------------------------------------------------------
# Generalization set. Every `category`/`brand` slug below was chosen from
# the catalog's OWN display names (verified in main()), never from a
# resolver call.
# ---------------------------------------------------------------------
CASES: list[dict] = [
    # --- en_bare_product -------------------------------------------------
    case("en_bare_product", "en", "I need milk", raw="milk", cat_hint="milk",
         mode=EXACT, category="milk_29", note="canonical Milk / الألبان"),
    case("en_bare_product", "en", "show me some chocolate", raw="chocolate", cat_hint="chocolate",
         mode=EXACT, category="chocolate_2", note="canonical Chocolate / الشوكولاتة"),
    case("en_bare_product", "en", "I want rice", raw="rice", cat_hint="rice",
         mode=EXACT, category="rice", note="canonical Rice / الأرز"),
    case("en_bare_product", "en", "looking for eggs", raw="eggs", cat_hint="eggs",
         mode=EXACT, category="eggs", note="canonical Eggs / البيض"),
    case("en_bare_product", "en", "do you have honey", raw="honey", cat_hint="honey",
         mode=EXACT, category="honey_5698", note="canonical Honey / عسل"),

    # --- ar_bare_product -------------------------------------------------
    case("ar_bare_product", "ar", "عايز جبنة", raw="جبنة", cat_hint="جبنة",
         mode=EXACT, category="cheese", note="canonical Cheese / الأجبان"),
    case("ar_bare_product", "ar", "عايزة عسل", raw="عسل", cat_hint="عسل",
         mode=EXACT, category="honey_5698", note="canonical AR name is literally عسل"),
    case("ar_bare_product", "ar", "محتاج رز", raw="رز", cat_hint="رز",
         mode=EXACT, category="rice", note="canonical Rice / الأرز"),
    case("ar_bare_product", "ar", "فيه بيض؟", raw="بيض", cat_hint="بيض",
         mode=EXACT, category="eggs", note="canonical Eggs / البيض"),
    case("ar_bare_product", "ar", "عايز عصير", raw="عصير", cat_hint="عصير",
         mode=EXACT, category="juices_36",
         note="canonical Juices / العصائر -- singular عصير vs plural العصائر is a "
              "morphology difference, not an ambiguity: no other row denotes juice"),

    # --- code_switch -----------------------------------------------------
    case("code_switch", "mixed", "عايز milk من فضلك", raw="milk", cat_hint="milk",
         mode=EXACT, category="milk_29"),
    case("code_switch", "mixed", "do you have شوكولاتة", raw="شوكولاتة", cat_hint="شوكولاتة",
         mode=EXACT, category="chocolate_2"),
    case("code_switch", "mixed", "I want شاي please", raw="شاي", cat_hint="شاي",
         mode=EXACT, category="tea_5702", note="canonical Tea / الشاي"),
    case("code_switch", "mixed", "عندكم diapers؟", raw="diapers", cat_hint="diapers",
         mode=EXACT, category="diapers_1723", note="canonical Diapers / حفاضات الأطفال"),

    # --- explicit_brand (brand named outright; no category requested) -----
    case("explicit_brand", "en", "do you have anything from Juhayna", brand="Juhayna",
         mode=EXACT, expected_brand="juhayna", note="canonical alias 'Juhayna', 122 products"),
    case("explicit_brand", "en", "I want Pepsi", brand="Pepsi",
         mode=EXACT, expected_brand="pepsi", note="11 products"),
    case("explicit_brand", "en", "anything from Dove", brand="Dove",
         mode=EXACT, expected_brand="dove", note="156 products"),
    case("explicit_brand", "ar", "عايز حاجة من جهينه", brand="جهينه",
         mode=EXACT, expected_brand="juhayna", note="جهينه IS a catalog brand_alias"),
    case("explicit_brand", "en", "do you have Al Tahhan products", brand="Al Tahhan",
         mode=EXACT, expected_brand="al_tahhan", note="obscure but real, 53 products"),

    # --- brand_variant_spelling (intended brand unmistakable, spelling off) --
    case("brand_variant_spelling", "en", "do you have any Nestlle products", brand="Nestlle",
         mode=EXACT, expected_brand="nestle", note="one inserted letter vs alias 'Nestle'"),
    case("brand_variant_spelling", "en", "anything from Doev", brand="Doev",
         mode=EXACT, expected_brand="dove", note="transposition of alias 'Dove'"),
    case("brand_variant_spelling", "en", "show me Juhaina", brand="Juhaina",
         mode=EXACT, expected_brand="juhayna", note="common transliteration variant"),
    case("brand_variant_spelling", "ar", "حاجة من نستله", brand="نستله",
         mode=EXACT, expected_brand="nestle",
         note="catalog AR alias is نيستل; نستله is the same brand, spelled differently"),

    # --- multi_word_concept ----------------------------------------------
    case("multi_word_concept", "en", "do you have cream cheese", raw="cream cheese", cat_hint="cream cheese",
         mode=AMBIG, acceptable_categories=["cream_spread_cheese_57", "cheese"],
         note="Cream & Spread Cheese denotes it, but generic Cheese is also a fair home"),
    case("multi_word_concept", "en", "I want greek yogurt", raw="greek yogurt", cat_hint="greek yogurt",
         mode=EXACT, category="greek_yogurt_50", acceptable_categories=["greek_yogurt_50", "yogurt"],
         note="Greek Yogurt / زبادي يوناني denotes it exactly; parent Yogurt not an error"),
    case("multi_word_concept", "en", "show me sliced cheese", raw="sliced cheese", cat_hint="sliced cheese",
         mode=EXACT, category="sliced_cheese_56", acceptable_categories=["sliced_cheese_56", "cheese"],
         note="Sliced Cheese / شرائح الجبن"),
    case("multi_word_concept", "en", "I need canned tuna", raw="canned tuna", cat_hint="canned tuna",
         mode=EXACT, category="tuna_canned_seafood_5691", note="Tuna & Canned Seafood / التونة"),
    case("multi_word_concept", "ar", "لبن خالي الدسم", raw="لبن خالي الدسم", cat_hint="لبن خالي الدسم",
         mode=EXACT, category="skimmed_milk_39", acceptable_categories=["skimmed_milk_39", "milk_29"],
         note="Skimmed Milk / لبن منزوع الدسم"),

    # --- ingredient_vs_descriptor ----------------------------------------
    case("ingredient_vs_descriptor", "en", "strawberry", raw="strawberry", cat_hint="fruits",
         mode=EXACT, category="fruits_3283", note="the fruit itself is the product"),
    case("ingredient_vs_descriptor", "en", "strawberry yogurt", raw="strawberry yogurt", cat_hint="yogurt",
         mode=AMBIG, acceptable_categories=["flavored_yogurt_49", "yogurt"],
         forbidden_categories=["fruits_3283"],
         note="strawberry is the FLAVOUR here; Flavored Yogurt and Yogurt both fair, Fruits is not"),
    case("ingredient_vs_descriptor", "en", "lemon", raw="lemon", cat_hint="fruits",
         mode=EXACT, category="fruits_3283", forbidden_categories=["vegetables_3286"],
         note="lemon is a fruit; Vegetables would be a wrong confident match"),
    case("ingredient_vs_descriptor", "en", "lemon dish soap", raw="lemon dish soap", cat_hint="dish soap",
         mode=EXACT, category="dishwashing_25", forbidden_categories=["fruits_3283"],
         note="lemon is the SCENT; Dishwashing / منتجات غسيل الأطباق is the product"),
    case("ingredient_vs_descriptor", "ar", "شامبو بالليمون", raw="شامبو بالليمون", cat_hint="شامبو",
         mode=AMBIG, acceptable_categories=["hair_care", "shower_bath_soap_1747"],
         forbidden_categories=["fruits_3283"],
         note="no row denotes shampoo alone; Hair Care and Shower/Bath/Soap both plausible"),

    # --- category_browse --------------------------------------------------
    case("category_browse", "en", "what's available in frozen food", raw="frozen food", cat_hint="frozen food",
         mode=EXACT, category="frozen_food_3281", note="Frozen Food / الأطعمة المجمدة"),
    case("category_browse", "en", "show me the beverages you carry", raw="beverages", cat_hint="beverages",
         mode=EXACT, category="beverages_35", note="Beverages / المشروبات"),
    case("category_browse", "ar", "وريني قسم المكسرات", raw="قسم المكسرات", cat_hint="مكسرات",
         mode=AMBIG, acceptable_categories=["nuts", "nuts_seeds_16871"],
         note="TWO rows denote nuts: `nuts` (مكسرات) and Nuts & Seeds (المكسرات)"),
    case("category_browse", "en", "what dairy products do you have", raw="dairy products", cat_hint="dairy",
         mode=AMBIG, acceptable_categories=["cheese_dairy_eggs_30", "milk_29"],
         note="Cheese, Dairy & Eggs denotes dairy; Milk's AR name is الألبان (dairy) too"),

    # --- free_from --------------------------------------------------------
    case("free_from", "en", "sugar-free chocolate please", raw="chocolate", cat_hint="chocolate",
         free_from="sugar", mode=EXACT, category="sugar_free_1736",
         note="Sugar Free / خالي من السكر is a real category, 46 products"),
    case("free_from", "en", "bread with no gluten", raw="bread", cat_hint="bread",
         free_from="gluten", mode=EXACT, category="gluten_free_27956",
         note="Gluten Free / خالي من الجلوتين, 19 products"),
    case("free_from", "ar", "عايز لبن من غير لاكتوز", raw="لبن", cat_hint="لبن",
         free_from="لاكتوز", mode=EXACT, category="lactose_free_32297",
         note="Lactose Free / خالي من اللاكتوز, 3 products"),
    case("free_from", "ar", "خبز خالي من الجلوتين", raw="خبز", cat_hint="خبز",
         free_from="جلوتين", mode=EXACT, category="gluten_free_27956"),
    case("free_from", "en", "milk with no added lactose please", raw="milk", cat_hint="milk",
         free_from="lactose", mode=EXACT, category="lactose_free_32297"),

    # --- typo_en (raw keeps the typo; the meant concept is unmistakable) ---
    case("typo_en", "en", "I need chese please", raw="chese", cat_hint="cheese",
         mode=EXACT, category="cheese"),
    case("typo_en", "en", "yogourt please", raw="yogourt", cat_hint="yogurt",
         mode=EXACT, category="yogurt", acceptable_categories=["yogurt"],
         note="generic yogurt request -> the generic Yogurt row denotes it"),
    case("typo_en", "en", "show me buttter", raw="buttter", cat_hint="butter",
         mode=EXACT, category="butter", note="Butter / الزبدة"),
    case("typo_en", "en", "looking for irce", raw="irce", cat_hint="rice",
         mode=EXACT, category="rice"),

    # --- typo_ar ----------------------------------------------------------
    case("typo_ar", "ar", "عايز بجنة", raw="بجنة", cat_hint="جبنة",
         mode=EXACT, category="cheese", note="transposition of جبنة"),
    case("typo_ar", "ar", "فيه رص؟", raw="رص", cat_hint="رز",
         mode=EXACT, category="rice", note="substitution in رز"),
    case("typo_ar", "ar", "عايز شاء", raw="شاء", cat_hint="شاي",
         mode=EXACT, category="tea_5702", note="substitution in شاي"),
    case("typo_ar", "ar", "محتاج عصل", raw="عصل", cat_hint="عسل",
         mode=EXACT, category="honey_5698", note="substitution in عسل"),

    # --- conversational_modify_replace ------------------------------------
    case("conversational_modify_replace", "en", "also add cheese", history=["I need milk"],
         intent=ADD, raw="cheese", cat_hint="cheese", mode=EXACT, category="cheese"),
    case("conversational_modify_replace", "ar", "كمان عايز عسل", history=["عايز لبن"],
         intent=ADD, raw="عسل", cat_hint="عسل", mode=EXACT, category="honey_5698"),
    case("conversational_modify_replace", "en", "make it under 80 instead",
         history=["I need milk under 50"], intent=MOD, price_max=80.0, mode=NONE),
    case("conversational_modify_replace", "ar", "لأ عايز عصير بدل كده", history=["عايز جبنة"],
         intent=MOD, raw="عصير", cat_hint="عصير", mode=EXACT, category="juices_36",
         note="replacement: the NEW product is the one before بدل"),
    case("conversational_modify_replace", "en", "never mind the brand",
         history=["milk from Juhayna"], intent=REM, target_facet="brand", mode=NONE),
    case("conversational_modify_replace", "en", "actually I need cat food",
         history=["I want chocolate"], intent=SEARCH, raw="cat food", cat_hint="cat food",
         mode=EXACT, category="cat_food_10486", note="topic switch; Cat Food / طعام القطط"),

    # --- price_only -------------------------------------------------------
    case("price_only", "en", "anything under 15 pounds", price_max=15.0, mode=NONE),
    case("price_only", "ar", "بين ثلاثين وستين جنيه", price_min=30.0, price_max=60.0, mode=NONE),
    case("price_only", "en", "I don't want to spend more than 200", price_max=200.0, mode=NONE),

    # --- off_topic --------------------------------------------------------
    case("off_topic", "en", "what time do you close?", intent=OFF, mode=NONE),
    case("off_topic", "en", "how's the weather in Cairo today?", intent=OFF, mode=NONE),
    case("off_topic", "ar", "احكيلي حاجة مضحكة", intent=OFF, mode=NONE),

    # --- product_word_resembling_brand (precision traps) -------------------
    case("product_word_resembling_brand", "en", "I want peas", raw="peas", cat_hint="peas",
         mode=RETRIEVAL, acceptable_categories=["vegetables_3286", "frozen_vegetables_11674"],
         forbidden_brands=["pears"],
         note="no canonical row denotes peas; `pears` is a real 2-product BRAND, not this"),
    case("product_word_resembling_brand", "ar", "بلدي جبنة", raw="بلدي جبنة", cat_hint="جبنة",
         mode=EXACT, category="cheese", forbidden_brands=["lady"],
         note="بلدي is a descriptor on real products, not the brand Lady"),
    case("product_word_resembling_brand", "ar", "رمان طازة", raw="رمان طازة", cat_hint="رمان",
         mode=RETRIEVAL, acceptable_categories=["fruits_3283"], forbidden_brands=["herman"],
         note="no pomegranate row; Fruits is the broader home; Herman is an unrelated brand"),
    case("product_word_resembling_brand", "en", "I want corn", raw="corn", cat_hint="corn",
         mode=RETRIEVAL, acceptable_categories=["vegetables_3286", "frozen_vegetables_11674"],
         note="no canonical row denotes corn"),
]

# ---------------------------------------------------------------------
# Historical bugs, kept separate from the generalization split.
# ---------------------------------------------------------------------
REGRESSION_CASES: list[dict] = [
    case("regression_tomato_paste_vs_pasta", "en", "tomato paste from Heinz",
         raw="tomato paste", cat_hint="tomato paste", brand="Heinz",
         mode=RETRIEVAL, expected_brand="heinz",
         acceptable_categories=["sauces_pastes_5694"], forbidden_categories=["pasta_5699"],
         note="original bug: 'paste' fuzzy-hijacked by the Pasta row"),
    case("regression_peas_vs_pears", "en", "peas", raw="peas", cat_hint="peas",
         mode=RETRIEVAL, acceptable_categories=["vegetables_3286"], forbidden_brands=["pears"],
         note="original bug: resolved to the brand Pears"),
    case("regression_frozen_peas", "en", "frozen peas", raw="frozen peas", cat_hint="frozen vegetables",
         mode=EXACT, category="frozen_vegetables_11674", forbidden_brands=["pears"],
         note="Frozen Vegetables / خضراوات مجمدة denotes it exactly"),
    case("regression_extra_virgin_olive_oil", "en", "extra virgin olive oil",
         raw="extra virgin olive oil", cat_hint="olive oil",
         mode=EXACT, category="oil_5685", forbidden_brands=["extra"],
         note="original bug: 'extra' hijacked by the real 15-product brand Extra"),
    case("regression_choclate_milk", "en", "choclate milk", raw="choclate milk", cat_hint="chocolate milk",
         mode=RETRIEVAL, acceptable_categories=["flavored_milk_41", "milk_29", "chocolate_2"],
         forbidden_brands=["chocodate"],
         note="original bug: 'choclate' hijacked by the brand Chocodate"),
    case("regression_alwadi_vs_el_bawadi", "ar", "عايز حاجة من الوادي", brand="الوادي",
         mode=RETRIEVAL, forbidden_brands=["el_bawadi"],
         note="el_bawadi's real aliases are البوادى / El Bawadi -- NOT الوادي, so no "
              "canonical brand denotes this; any brand match here is a false hijack"),
]


def fetch_catalog_evidence() -> tuple[dict, dict]:
    """Authoritative catalog truth, read straight from the database. Used
    ONLY to verify hand-authored slugs and attach evidence -- never to
    choose or derive a label."""
    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT cc.slug, cc.display_name_en, cc.display_name_ar,
                   COUNT(DISTINCT pcx.product_id)
            FROM canonical_category cc
            JOIN category c ON c.canonical_category_id = cc.id
            LEFT JOIN product_category pcx ON pcx.category_id = c.id
            GROUP BY cc.slug, cc.display_name_en, cc.display_name_ar
        """)
        categories = {
            slug: {"display_name_en": en, "display_name_ar": ar, "product_count": n}
            for slug, en, ar, n in cur.fetchall()
        }
        cur.execute("""
            SELECT cb.slug, COUNT(DISTINCT p.id)
            FROM canonical_brand cb
            LEFT JOIN product p ON p.brand_normalized = cb.slug
            GROUP BY cb.slug
        """)
        brand_counts = dict(cur.fetchall())
        cur.execute("""
            SELECT cb.slug, ba.raw_value
            FROM brand_alias ba JOIN canonical_brand cb ON cb.id = ba.canonical_brand_id
        """)
        aliases: dict[str, list[str]] = {}
        for slug, raw in cur.fetchall():
            aliases.setdefault(slug, []).append(raw)
    brands = {
        slug: {"product_count": n, "aliases": sorted(aliases.get(slug, []))}
        for slug, n in brand_counts.items()
    }
    return categories, brands


def verify_and_attach(cases: list[dict], categories: dict, brands: dict) -> list[str]:
    """Every referenced slug must exist in the catalog. A positively
    asserted grounding must also back real products (a zero-product row
    could never be a correct answer). Forbidden slugs are only required to
    EXIST -- that they denote something real is exactly what makes them a
    hijack risk worth naming."""
    problems: list[str] = []
    for c in cases:
        g = c["expected_grounding"]
        evidence = {"categories": {}, "brands": {}}

        positive_cats = [g["category"]] if g["category"] else []
        positive_cats += list(g["acceptable_categories"])
        for slug in positive_cats:
            info = categories.get(slug)
            if info is None:
                problems.append(f"{c['sentence']!r}: unknown category slug {slug!r}")
                continue
            if info["product_count"] == 0:
                problems.append(f"{c['sentence']!r}: category {slug!r} backs zero products")
            evidence["categories"][slug] = info

        positive_brands = [g["brand"]] if g["brand"] else []
        positive_brands += list(g["acceptable_brands"])
        for slug in positive_brands:
            info = brands.get(slug)
            if info is None:
                problems.append(f"{c['sentence']!r}: unknown brand slug {slug!r}")
                continue
            if info["product_count"] == 0:
                problems.append(f"{c['sentence']!r}: brand {slug!r} backs zero products")
            evidence["brands"][slug] = info

        for slug in g["forbidden_categories"]:
            if slug in categories:
                evidence["categories"][slug] = categories[slug]
            else:
                problems.append(f"{c['sentence']!r}: unknown forbidden category {slug!r}")
        for slug in g["forbidden_brands"]:
            if slug in brands:
                evidence["brands"][slug] = brands[slug]
            else:
                problems.append(f"{c['sentence']!r}: unknown forbidden brand {slug!r}")

        # Mode invariants -- keeps the "what is exactly recallable" contract honest.
        mode = g["mode"]
        if mode == EXACT and not (g["category"] or g["brand"]):
            problems.append(f"{c['sentence']!r}: mode=exact but nothing asserted")
        if mode in (AMBIG, RETRIEVAL, NONE) and g["category"]:
            problems.append(f"{c['sentence']!r}: mode={mode} must not assert an exact category")

        c["catalog_evidence"] = evidence
    return problems


def main() -> None:
    categories, brands = fetch_catalog_evidence()
    log(f"Catalog evidence: {len(categories)} referenced categories, {len(brands)} brands.")

    problems = verify_and_attach(CASES, categories, brands)
    problems += verify_and_attach(REGRESSION_CASES, categories, brands)
    if problems:
        for p in problems:
            log(f"  LABEL ERROR: {p}")
        raise SystemExit(f"{len(problems)} label(s) failed catalog verification -- nothing written.")
    log("All hand-authored slugs verified against the database.")

    for i, c in enumerate(CASES):
        c["id"] = i + 1
    for i, c in enumerate(REGRESSION_CASES):
        c["id"] = 1000 + i + 1

    rng = random.Random(SEED)
    shuffled = CASES[:]
    rng.shuffle(shuffled)
    n_dev = round(len(shuffled) * DEV_FRACTION)
    dev = sorted(shuffled[:n_dev], key=lambda c: c["id"])
    holdout = sorted(shuffled[n_dev:], key=lambda c: c["id"])

    modes: dict[str, int] = {}
    for c in CASES + REGRESSION_CASES:
        modes[c["expected_grounding"]["mode"]] = modes.get(c["expected_grounding"]["mode"], 0) + 1
    log(f"Split: {len(dev)} dev / {len(holdout)} holdout / {len(REGRESSION_CASES)} regression "
        f"(seed={SEED}). Modes across all cases: {modes}")

    out = ROOT / "evaluation"
    meta = {"seed": SEED, "dev_fraction": DEV_FRACTION,
            "label_policy": "roles from intended user meaning; groundings hand-authored from "
                            "canonical catalog display names and verified against the database; "
                            "no production resolver was called to produce any expected value"}
    (out / "sprint6_semantic_benchmark_v2_dev.json").write_text(
        json.dumps({**meta, "cases": dev}, ensure_ascii=False, indent=2), encoding="utf-8")
    holdout_path = out / "sprint6_semantic_benchmark_v2_holdout.json"
    holdout_path.write_text(
        json.dumps({**meta, "cases": holdout}, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "sprint6_semantic_benchmark_v2_regression.json").write_text(
        json.dumps({**meta, "cases": REGRESSION_CASES}, ensure_ascii=False, indent=2), encoding="utf-8")

    sha256 = hashlib.sha256(holdout_path.read_bytes()).hexdigest()
    (out / "sprint6_semantic_benchmark_v2_holdout.sha256.txt").write_text(sha256 + "\n", encoding="utf-8")
    log(f"FROZEN holdout SHA-256: {sha256}")


if __name__ == "__main__":
    main()

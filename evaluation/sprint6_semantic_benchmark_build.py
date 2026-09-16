"""Sprint 6 POST-REFACTOR semantic benchmark -- builds and FREEZES a new
evaluation set for the role-based Understanding+Validation architecture.
Evaluation artifact only, never imported by production code.

Ground truth is authored in two layers, deliberately kept independent:
  - "roles": the semantic roles a correct LLM call SHOULD produce for this
    sentence (raw_query_text / category_hint / brand_text / free_from) --
    hand-authored here, used to grade metric (A) semantic extraction
    accuracy against the REAL model's actual output.
  - "expected_category" / "expected_brand": computed at build time by
    running the SAME production resolvers (resolve_category_hint /
    resolve_brand_text / resolve_free_from) against the hand-authored
    roles above -- never hand-typed as catalog slugs, so there is no
    hand-transcription error against the live catalog. This is the
    objective target for metric (B) catalog-grounding accuracy: does
    validate() applied to the model's ACTUAL output land on the same
    catalog entity as validate() applied to the intended roles.

Historical bug sentences (the 4 originally-reported failures plus 2 more
from the Sprint 6 generalization audit) are kept as a separate
"regression" bucket -- always run, never counted in the headline
dev/holdout generalization numbers, per the task's explicit instruction
not to blend known-bug regression tests into the generalization proof.

Usage: python evaluation/sprint6_semantic_benchmark_build.py
Writes: evaluation/sprint6_semantic_benchmark_dev.json
        evaluation/sprint6_semantic_benchmark_holdout.json (FROZEN)
        evaluation/sprint6_semantic_benchmark_holdout.sha256.txt
        evaluation/sprint6_semantic_benchmark_regression.json
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.search_engine.keyword_baseline import (  # noqa: E402
    resolve_brand_text, resolve_category_hint, resolve_free_from,
)

SEED = 20260921
DEV_FRACTION = 0.70


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


# Each case: (tag, sentence, history_or_None, ambiguous,
#             intent, price_min, price_max, target_facet,
#             raw_role, cat_role, brand_role, free_from_role)
# role fields are the INTENDED semantic roles (ground truth for metric A);
# None means that role should be absent.

C = "search"
ADD = "add_filter"
MOD = "modify_filter"
REM = "remove_filter"
RESET = "reset"
OFF = "off_topic"

CASES: list[tuple] = [
    # --- en_bare_product ---
    ("en_bare_product", "I need milk", None, False, C, None, None, None, "milk", "milk", None, None),
    ("en_bare_product", "show me some chocolate", None, False, C, None, None, None, "chocolate", "chocolate", None, None),
    ("en_bare_product", "do you have yogurt", None, False, C, None, None, None, "yogurt", "yogurt", None, None),
    ("en_bare_product", "I want rice", None, False, C, None, None, None, "rice", "rice", None, None),
    ("en_bare_product", "looking for eggs", None, False, C, None, None, None, "eggs", "eggs", None, None),
    ("en_bare_product", "any butter available", None, False, C, None, None, None, "butter", "butter", None, None),

    # --- ar_bare_product ---
    ("ar_bare_product", "عايز جبنة", None, False, C, None, None, None, "جبنة", "جبنة", None, None),
    # ambiguous: the catalog's generic "yogurt" category name is a multi-word
    # phrase ("منتجات الزبادي"), and 3 more specific yogurt-variety categories
    # also exist (Greek/Plain/Flavored) -- which one a bare "زبادي" should hit
    # is genuinely underdetermined, not a clean single-answer recall case.
    ("ar_bare_product", "عندكم زبادي؟", None, True, C, None, None, None, "زبادي", "زبادي", None, None),
    ("ar_bare_product", "عايزة عسل", None, False, C, None, None, None, "عسل", "عسل", None, None),
    ("ar_bare_product", "محتاج رز", None, False, C, None, None, None, "رز", "رز", None, None),
    ("ar_bare_product", "فيه بيض؟", None, False, C, None, None, None, "بيض", "بيض", None, None),
    ("ar_bare_product", "عايز تمر", None, False, C, None, None, None, "تمر", "تمر", None, None),

    # --- code_switch ---
    ("code_switch", "عايز milk من فضلك", None, False, C, None, None, None, "milk", "milk", None, None),
    ("code_switch", "do you have شوكولاتة", None, False, C, None, None, None, "شوكولاتة", "شوكولاتة", None, None),
    ("code_switch", "I want شاي please", None, False, C, None, None, None, "شاي", "شاي", None, None),
    ("code_switch", "عندكم diapers؟", None, False, C, None, None, None, "diapers", "diapers", None, None),
    ("code_switch", "give me عسل please", None, False, C, None, None, None, "عسل", "عسل", None, None),
    ("code_switch", "عايز يعني some جبنة", None, False, C, None, None, None, "جبنة", "جبنة", None, None),

    # --- explicit_brand_common ---
    ("explicit_brand_common", "do you have anything from Juhayna", None, False, C, None, None, None, None, None, "Juhayna", None),
    ("explicit_brand_common", "I want Pepsi", None, False, C, None, None, None, None, None, "Pepsi", None),
    ("explicit_brand_common", "show me Nestle products", None, False, C, None, None, None, None, None, "Nestle", None),
    ("explicit_brand_common", "anything from Dove", None, False, C, None, None, None, None, None, "Dove", None),
    ("explicit_brand_common", "عايز حاجة من جهينة", None, False, C, None, None, None, None, None, "جهينة", None),
    ("explicit_brand_common", "حاجة من نستله لو سمحت", None, False, C, None, None, None, None, None, "نستله", None),

    # --- explicit_brand_obscure ---
    ("explicit_brand_obscure", "do you have Al Tahhan products", None, False, C, None, None, None, None, None, "Al Tahhan", None),
    ("explicit_brand_obscure", "anything from Abo Bint", None, False, C, None, None, None, None, None, "Abo Bint", None),
    ("explicit_brand_obscure", "I want something from Ashha", None, False, C, None, None, None, None, None, "Ashha", None),
    ("explicit_brand_obscure", "anything from Bahi?", None, False, C, None, None, None, None, None, "Bahi", None),
    ("explicit_brand_obscure", "do you carry Abo Alwalad?", None, False, C, None, None, None, None, None, "Abo Alwalad", None),

    # --- brand_typo (real brand, one edit away) ---
    ("brand_typo", "do you have any Nestlle products", None, False, C, None, None, None, None, None, "Nestlle", None),
    ("brand_typo", "I want Pepsii", None, False, C, None, None, None, None, None, "Pepsii", None),
    ("brand_typo", "anything from Doev", None, False, C, None, None, None, None, None, "Doev", None),
    ("brand_typo", "show me Juhaina", None, False, C, None, None, None, None, None, "Juhaina", None),
    ("brand_typo", "I need Colgat toothpaste", None, False, C, None, None, None, "toothpaste", "toothpaste", "Colgat", None),
    ("brand_typo", "حاجة من جهينه", None, False, C, None, None, None, None, None, "جهينه", None),

    # --- product_word_resembling_brand (fuzzy-collision traps) ---
    # category_hint role is the head-noun generalization ("vegetables"), not
    # the literal word, matching the design's own "cucumber" -> "vegetables"
    # pattern -- confirmed this is what the real model actually produces.
    ("product_word_resembling_brand", "I want peas", None, False, C, None, None, None, "peas", "vegetables", None, None),
    ("product_word_resembling_brand", "بلدي جبنة", None, False, C, None, None, None, "بلدي جبنة", "جبنة", None, None),
    ("product_word_resembling_brand", "كراميل حلويات", None, False, C, None, None, None, "كراميل حلويات", "حلويات", None, None),
    ("product_word_resembling_brand", "رمان طازة", None, False, C, None, None, None, "رمان طازة", "رمان", None, None),
    ("product_word_resembling_brand", "I want corn", None, False, C, None, None, None, "corn", "corn", None, None),

    # --- category_only (browsing a department, no specific product) ---
    ("category_only", "what's in your bakery section", None, True, C, None, None, None, "bakery section", "bakery", None, None),
    ("category_only", "show me the beverages you carry", None, True, C, None, None, None, "beverages", "beverages", None, None),
    ("category_only", "what dairy products do you have", None, True, C, None, None, None, "dairy products", "dairy", None, None),
    ("category_only", "عندكم منتجات ألبان ايه؟", None, True, C, None, None, None, "منتجات ألبان", "ألبان", None, None),
    ("category_only", "وريني قسم المكسرات", None, True, C, None, None, None, "قسم المكسرات", "مكسرات", None, None),
    ("category_only", "what's available in frozen food", None, True, C, None, None, None, "frozen food", "frozen food", None, None),

    # --- multi_word_concept (one concept, stays whole) ---
    ("multi_word_concept", "do you have cream cheese", None, True, C, None, None, None, "cream cheese", "cheese", None, None),
    ("multi_word_concept", "I want greek yogurt", None, True, C, None, None, None, "greek yogurt", "greek yogurt", None, None),
    ("multi_word_concept", "show me sliced cheese", None, True, C, None, None, None, "sliced cheese", "sliced cheese", None, None),
    ("multi_word_concept", "I need canned tuna", None, True, C, None, None, None, "canned tuna", "tuna", None, None),
    ("multi_word_concept", "لبن خالي الدسم", None, True, C, None, None, None, "لبن خالي الدسم", "لبن", None, None),
    ("multi_word_concept", "جبنة قريش طازة", None, True, C, None, None, None, "جبنة قريش طازة", "جبنة", None, None),

    # --- ingredient_vs_product (same word, role depends on context) ---
    ("ingredient_vs_product", "strawberry", None, False, C, None, None, None, "strawberry", "fruits", None, None),
    ("ingredient_vs_product", "strawberry yogurt", None, False, C, None, None, None, "strawberry yogurt", "yogurt", None, None),
    ("ingredient_vs_product", "lemon", None, False, C, None, None, None, "lemon", "fruits", None, None),
    ("ingredient_vs_product", "lemon dish soap", None, False, C, None, None, None, "lemon dish soap", "dishwashing", None, None),
    # ambiguous: no single obviously-correct category exists for "shampoo"
    # in this catalog (hair_care / personal_care / shower_bath_soap are all
    # plausible) -- a genuine taxonomy question, not a clean recall case.
    ("ingredient_vs_product", "شامبو بالليمون", None, True, C, None, None, None, "شامبو بالليمون", "شامبو", None, None),
    ("ingredient_vs_product", "ليمون", None, False, C, None, None, None, "ليمون", "فاكهة", None, None),

    # --- free_from ---
    ("free_from", "sugar-free chocolate please", None, False, C, None, None, None, "chocolate", "chocolate", None, "sugar"),
    ("free_from", "bread with no gluten", None, False, C, None, None, None, "bread", "bread", None, "gluten"),
    ("free_from", "milk with no added sugar", None, False, C, None, None, None, "milk", "milk", None, "sugar"),
    ("free_from", "عايز لبن من غير لاكتوز", None, False, C, None, None, None, "لبن", "لبن", None, "لاكتوز"),
    ("free_from", "خبز خالي من الجلوتين", None, False, C, None, None, None, "خبز", "خبز", None, "جلوتين"),
    ("free_from", "يوجرت بدون لاكتوز لو سمحت", None, False, C, None, None, None, "يوجرت", "يوجرت", None, "لاكتوز"),

    # --- price ---
    ("price", "milk between 20 and 40", None, False, C, 20.0, 40.0, None, "milk", "milk", None, None),
    ("price", "anything under 15 pounds", None, False, C, None, 15.0, None, None, None, None, None),
    ("price", "I don't want to spend more than 200", None, False, C, None, 200.0, None, None, None, None, None),
    ("price", "at least 75 pounds please", None, False, C, 75.0, None, None, None, None, None, None),
    ("price", "بين ثلاثين وستين جنيه", None, False, C, 30.0, 60.0, None, None, None, None, None),
    ("price", "مش عايز أصرف أكتر من ٤٥", None, False, C, None, 45.0, None, None, None, None, None),

    # --- typo_en (unseen mutation, product word only; category_hint is the
    # LLM's own corrected semantic reading, raw_query_text keeps the typo) ---
    ("typo_en", "I need chese please", None, False, C, None, None, None, "chese", "cheese", None, None),
    ("typo_en", "yogourt please", None, False, C, None, None, None, "yogourt", "yogurt", None, None),
    ("typo_en", "I want browne bread", None, False, C, None, None, None, "browne bread", "bread", None, None),
    ("typo_en", "looking for irce", None, False, C, None, None, None, "irce", "rice", None, None),
    ("typo_en", "show me buttter", None, False, C, None, None, None, "buttter", "butter", None, None),
    ("typo_en", "I need bananna", None, False, C, None, None, None, "bananna", "fruits", None, None),

    # --- typo_ar (unseen mutation, product word) ---
    ("typo_ar", "عايز بجنة", None, False, C, None, None, None, "بجنة", "جبنة", None, None),
    ("typo_ar", "محتاج زابدي", None, True, C, None, None, None, "زابدي", "زبادي", None, None),  # same yogurt-variety ambiguity as عندكم زبادي؟
    ("typo_ar", "عايز عصار", None, False, C, None, None, None, "عصار", "عصير", None, None),
    ("typo_ar", "فيه رص؟", None, False, C, None, None, None, "رص", "رز", None, None),
    ("typo_ar", "عايز شاء", None, False, C, None, None, None, "شاء", "شاي", None, None),
    ("typo_ar", "محتاج عصل", None, False, C, None, None, None, "عصل", "عسل", None, None),

    # --- multiword_one_typo (multi-word query, ONE word misspelled --
    # Finding D's specific failure mode: per-token OR match is non-empty
    # because the other word(s) match literally, so the misspelled token
    # never reaches spelling correction today) ---
    ("multiword_one_typo", "fresh chiken breast", None, False, C, None, None, None, "fresh chiken breast", "chicken", None, None),
    ("multiword_one_typo", "browne sugar please", None, False, C, None, None, None, "browne sugar", "sugar", None, None),
    ("multiword_one_typo", "extra virgn olive oil", None, False, C, None, None, None, "extra virgn olive oil", "olive oil", None, None),
    ("multiword_one_typo", "sliced chesse please", None, True, C, None, None, None, "sliced chesse", "sliced cheese", None, None),
    ("multiword_one_typo", "عايز جبنة رومي طاز", None, True, C, None, None, None, "جبنة رومي طاز", "جبنة", None, None),
    ("multiword_one_typo", "فول سوداني محمس", None, True, C, None, None, None, "فول سوداني محمس", "فول سوداني", None, None),

    # --- add_modify_remove_reset (with history) ---
    ("add_modify_remove_reset", "also add cheese", ["I need milk"], False, ADD, None, None, None, "cheese", "cheese", None, None),
    ("add_modify_remove_reset", "كمان عايز عسل", ["عايز لبن"], False, ADD, None, None, None, "عسل", "عسل", None, None),
    ("add_modify_remove_reset", "make it under 80 instead", ["I need milk under 50"], False, MOD, None, 80.0, None, None, None, None, None),
    ("add_modify_remove_reset", "لأ عايز زبادي بدل كده", ["عايز جبنة"], True, MOD, None, None, None, "زبادي", "زبادي", None, None),  # same yogurt-variety ambiguity
    ("add_modify_remove_reset", "never mind the brand", ["milk from Juhayna"], False, REM, None, None, "brand", None, None, None, None),
    ("add_modify_remove_reset", "امسح السعر", ["عايز جبنة تحت ٥٠"], False, REM, None, None, "price", None, None, None, None),
    ("add_modify_remove_reset", "let's start fresh", ["I need milk", "under 50"], False, RESET, None, None, None, None, None, None, None),
    ("add_modify_remove_reset", "بلاش كل ده، من الأول", ["عايز عصير"], False, RESET, None, None, None, None, None, None, None),

    # --- topic_switch (unrelated department, discards prior filters) ---
    ("topic_switch", "actually forget it, show me detergent", ["I need milk", "under 50"], False, C, None, None, None, "detergent", "detergent", None, None),
    ("topic_switch", "خلاص سيبك من اللبن، عايز شامبو", ["عايز لبن"], True, C, None, None, None, "شامبو", "شامبو", None, None),  # same shampoo taxonomy ambiguity
    ("topic_switch", "never mind, I need diapers instead", ["milk from Juhayna"], False, C, None, None, None, "diapers", "diapers", None, None),
    # ambiguous: "paper tissues" plausibly maps to tissues_wipes / toilet_rolls
    # / tissues_wipes_rolls -- more than one real candidate, no single answer.
    ("topic_switch", "طيب وريني مناديل ورقية بدل كده", ["عايز جبنة تحت ٣٠"], True, C, None, None, None, "مناديل ورقية", "مناديل ورقية", None, None),
    ("topic_switch", "actually I need cat food", ["I want chocolate"], False, C, None, None, None, "cat food", "cat food", None, None),

    # --- off_topic ---
    ("off_topic", "what time do you close?", None, False, OFF, None, None, None, None, None, None, None),
    ("off_topic", "do you deliver to Alexandria?", None, False, OFF, None, None, None, None, None, None, None),
    ("off_topic", "مبروك عليكم الافتتاح الجديد", None, False, OFF, None, None, None, None, None, None, None),
    ("off_topic", "احكيلي حاجة مضحكة", None, False, OFF, None, None, None, None, None, None, None),
    ("off_topic", "how's the weather in Cairo today?", None, False, OFF, None, None, None, None, None, None, None),
]

# Historical bug regressions -- always run, never in the dev/holdout split.
REGRESSION_CASES: list[tuple] = [
    ("regression_tomato_paste", "tomato paste from Heinz", None, False, C, None, None, None, "tomato paste", "tomato paste", "Heinz", None),
    ("regression_peas_pears", "peas", None, False, C, None, None, None, "peas", "vegetables", None, None),
    ("regression_frozen_peas", "frozen peas", None, False, C, None, None, None, "frozen peas", "frozen vegetables", None, None),
    ("regression_extra_virgin_olive_oil", "extra virgin olive oil", None, False, C, None, None, None, "extra virgin olive oil", "olive oil", None, None),
    ("regression_choclate_milk", "choclate milk", None, False, C, None, None, None, "choclate milk", "milk", None, None),
    ("regression_wadi_bawadi", "عايز حاجة من الوادي", None, False, C, None, None, None, None, None, "الوادي", None),
]


# A handful of cases need a ground-truth override rather than the
# auto-derived value: computing "expected" by resolving the case's own
# role text is circular exactly when that role text IS the thing under
# test (a typo) and the resolver currently fails on it -- the auto-derived
# "expected" would then just equal the failure, silently hiding a real
# miss as a false "pass". Overrides hold the objectively correct,
# hand-verified target instead. Keyed by sentence (unique in this dataset).
GROUND_TRUTH_OVERRIDES: dict[str, dict] = {
    # "Doev" is a deliberate one-edit typo of the real brand "Dove" --
    # the intended answer is unambiguously "dove", not whatever (if
    # anything) the typo itself happens to fuzzy-match today.
    "anything from Doev": {"brand": "dove"},
    # Bare Arabic "ليمون" (lemon): the English "lemon"/"strawberry" cases
    # above confirm fruits_3283 is reachable, but the Arabic singular word
    # doesn't fuzzy-match the catalog's plural+prefix Arabic name for the
    # same category ("الفواكه") -- a morphology gap, not real ambiguity.
    "ليمون": {"category": "fruits_3283"},
    # Same head-noun-generalization pattern discovered on "peas" above,
    # confirmed against real dev-set model output: the model correctly
    # generalizes to the category name rather than repeating the literal
    # word (or, for "عايز عصار", the fuzzy resolver tolerates the typo
    # directly) -- these are genuine correct outcomes my conservative
    # None-expectation didn't anticipate, not real false matches.
    "رمان طازة": {"category": "fruits_3283"},
    "I want corn": {"category": "vegetables_3286"},
    "عايز عصار": {"category": "juices_36"},
}


def build_case(idx: int, tag: str, sentence: str, history, ambiguous: bool,
                intent: str, price_min, price_max, target_facet,
                raw_role, cat_role, brand_role, free_from_role) -> dict:
    expected_category = None
    if free_from_role:
        expected_category = resolve_free_from(free_from_role)
    category_from_hint = expected_category is None
    if category_from_hint and cat_role:
        expected_category = resolve_category_hint(cat_role)
    expected_brand = resolve_brand_text(brand_role) if brand_role else None

    override = GROUND_TRUTH_OVERRIDES.get(sentence)
    if override:
        expected_category = override.get("category", expected_category)
        expected_brand = override.get("brand", expected_brand)

    return {
        "id": idx,
        "tag": tag,
        "sentence": sentence,
        "history": history,
        "ambiguous": ambiguous,
        "expected": {
            "intent": intent,
            "price_min": price_min,
            "price_max": price_max,
            "target_facet": target_facet,
        },
        "roles": {
            "raw_query_text": raw_role,
            "category_hint": cat_role,
            "brand_text": brand_role,
            "free_from": free_from_role,
        },
        "expected_grounding": {
            "category": expected_category,
            "brand": expected_brand,
            "unresolved_exclusion": bool(free_from_role) and expected_category is None,
        },
    }


def main() -> None:
    rng = random.Random(SEED)

    cases = [build_case(i + 1, *c) for i, c in enumerate(CASES)]
    regression = [build_case(1000 + i + 1, *c) for i, c in enumerate(REGRESSION_CASES)]

    log(f"Authored {len(cases)} generalization cases across "
        f"{len({c['tag'] for c in cases})} tags, {len(regression)} regression cases.")

    shuffled = cases[:]
    rng.shuffle(shuffled)
    n_dev = round(len(shuffled) * DEV_FRACTION)
    dev = shuffled[:n_dev]
    holdout = shuffled[n_dev:]
    dev.sort(key=lambda c: c["id"])
    holdout.sort(key=lambda c: c["id"])

    log(f"Split: {len(dev)} dev / {len(holdout)} holdout (seed={SEED}, "
        f"fraction={DEV_FRACTION}).")

    out_dir = ROOT / "evaluation"
    dev_path = out_dir / "sprint6_semantic_benchmark_dev.json"
    holdout_path = out_dir / "sprint6_semantic_benchmark_holdout.json"
    regression_path = out_dir / "sprint6_semantic_benchmark_regression.json"

    dev_path.write_text(json.dumps({"seed": SEED, "cases": dev}, ensure_ascii=False, indent=2), encoding="utf-8")
    holdout_path.write_text(json.dumps({"seed": SEED, "cases": holdout}, ensure_ascii=False, indent=2), encoding="utf-8")
    regression_path.write_text(json.dumps({"cases": regression}, ensure_ascii=False, indent=2), encoding="utf-8")

    sha256 = hashlib.sha256(holdout_path.read_bytes()).hexdigest()
    (out_dir / "sprint6_semantic_benchmark_holdout.sha256.txt").write_text(sha256 + "\n", encoding="utf-8")

    log(f"Wrote {dev_path.name}, {holdout_path.name} (SHA-256: {sha256}), {regression_path.name}.")

    # Spot-check log of every computed expected_grounding, for manual review
    # before this is treated as frozen ground truth.
    review_lines = []
    for c in cases + regression:
        review_lines.append(
            f"[{c['tag']}] {c['sentence']!r} roles={c['roles']} "
            f"-> expected={c['expected_grounding']}"
        )
    (out_dir / "sprint6_semantic_benchmark_review.txt").write_text(
        "\n".join(review_lines), encoding="utf-8"
    )
    log(f"Wrote review log with {len(review_lines)} lines for manual spot-check.")


if __name__ == "__main__":
    main()

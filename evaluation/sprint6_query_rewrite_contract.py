"""Sprint 6 Module 1 -- QUERY REWRITE CONTRACT. Definition only: no
production code is touched by this file. It exists to state, BEFORE any
prompt/schema change, exactly what `product_query` is supposed to mean --
so Module 2's prompt work has a fixed target to write to, and Module 7's
dev evaluation has a fixed target to grade against.

======================================================================
THE CONTRACT
======================================================================

product_query = the shortest clear shopping phrase that preserves the
                 product the user intends to buy.

The rewrite MAY:
  - drop filler ("please", "can you show me", "something to drink")
  - normalize awkward/indirect phrasing into the plain product name
    ("something made from oats to drink" -> "oat milk")
  - keep a meaningful multi-word concept intact, in the user's own word
    order ("milk chocolate" stays "milk chocolate", never reordered to
    "chocolate milk" -- they are different products)

The rewrite MUST NOT:
  - invent a product, brand, or category that was never implied
  - freely correct spelling it is not certain about -- a typo'd product
    word is copied through UNCHANGED ("cucmber" -> "cucmber", never
    silently "corrected" to "cucumber"). Catalog-backed spelling recovery
    is the search layer's job (ranking.py), never this layer's guess.
  - fold a brand mention into product_query -- an explicit brand goes in
    brand_text and is removed from product_query (unchanged from the
    current raw_query_text contract)
  - fold an explicit exclusion into product_query -- goes in free_from

category_hint = the semantic category of the MAIN PRODUCT being bought,
                 in everyday words -- NOT product_query itself, and not a
                 canonical catalog slug. Ingredients, flavours, scents,
                 and materials that merely MODIFY the main product stay
                 inside product_query but do NOT drive category_hint:
                 "cucumber body lotion" is a lotion that happens to smell
                 of cucumber, not a vegetable. This is unchanged from the
                 existing category_hint contract -- restated here because
                 product_query changing (rewritten, not raw) must not be
                 allowed to also change what category_hint means.

Nothing here is a per-word dictionary. "oat -> milk", "cucumber ->
vegetables" are WORKED EXAMPLES of the general rule (find the main
product; a modifier isn't the product), not entries a production lookup
table is meant to contain.

======================================================================
CASE FIELDS
======================================================================
tag                    - which required category this case demonstrates
language               - en / ar / mixed
sentence               - the input message
product_query          - the CONTRACT's expected rewrite
typo_preserved         - True if product_query must reproduce the input's
                         misspelling verbatim (the rewrite rule's one hard
                         "do not touch this" case)
category_hint          - expected category_hint, or None if the message
                         names no product at all
category_hint_ambiguous - True if more than one real category plausibly
                         denotes the concept (excluded from any future
                         exact-match grading, same convention as the
                         Module 7/8 semantic benchmark)
brand_text             - expected brand_text, or None
free_from              - expected free_from, or None
note                   - why this is the expected answer
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def case(tag, lang, sentence, product_query, *, typo_preserved=False,
         category_hint=None, category_hint_ambiguous=False,
         brand_text=None, free_from=None, note="") -> dict:
    return {
        "tag": tag, "language": lang, "sentence": sentence,
        "product_query": product_query, "typo_preserved": typo_preserved,
        "category_hint": category_hint, "category_hint_ambiguous": category_hint_ambiguous,
        "brand_text": brand_text, "free_from": free_from, "note": note,
    }


CASES: list[dict] = [
    # --- simple product ---------------------------------------------------
    case("simple_product", "en", "I need milk", "milk",
         category_hint="milk", note="bare product, no rewrite needed"),
    case("simple_product", "en", "do you have yogurt", "yogurt",
         category_hint="yogurt"),

    # --- multi-word product (concept stays whole, order preserved) --------
    case("multi_word_product", "en", "I want cream cheese", "cream cheese",
         category_hint="cheese", note="one concept, not split into cream + cheese"),
    case("multi_word_product", "en", "milk chocolate", "milk chocolate",
         category_hint="chocolate", note="user example -- word order is meaningful"),
    case("multi_word_product", "en", "chocolate milk", "chocolate milk",
         category_hint="milk", note="user example -- the REVERSE of milk chocolate, a different product"),

    # --- product vs ingredient/descriptor (MAIN PRODUCT rule) -------------
    case("product_vs_ingredient", "en", "I need cucumber", "cucumber",
         category_hint="vegetables", note="user example -- cucumber IS the product"),
    case("product_vs_ingredient", "en", "I need cucumber body lotion", "cucumber body lotion",
         category_hint="body lotion",
         note="user example -- cucumber only scents the lotion; lotion is the MAIN PRODUCT"),
    case("product_vs_ingredient", "en", "strawberry yogurt", "strawberry yogurt",
         category_hint="yogurt", note="strawberry is the flavour, yogurt is the product"),
    case("product_vs_ingredient", "en", "lemon shampoo", "lemon shampoo",
         category_hint="shampoo", category_hint_ambiguous=True,
         note="lemon only scents the shampoo; 'shampoo' itself has no single obviously-correct "
              "canonical row in this catalog (hair care vs shower/bath/soap) -- ambiguous at the "
              "grounding layer, not at the rewrite layer"),

    # --- natural / messy wording (the rewrite's actual job) -----------------
    case("messy_wording", "en", "something made from oats to drink", "oat milk",
         category_hint="milk", note="user example -- indirect description rewritten to the plain product name"),
    case("messy_wording", "en", "can you please show me some extra virgin olive oil",
         "extra virgin olive oil", category_hint="olive oil",
         note="user example -- filler dropped, the multi-word concept itself untouched"),
    case("messy_wording", "en", "umm do you guys carry that spinneys own brand cheese or nah",
         "cheese", brand_text="spinneys own brand", category_hint="cheese",
         note="filler and hedging dropped; brand phrase goes to brand_text, not product_query"),

    # --- brand + product (brand is removed from product_query) ------------
    case("brand_plus_product", "en", "Heinz tomato paste", "tomato paste",
         brand_text="Heinz", category_hint="tomato paste", category_hint_ambiguous=True,
         note="brand extracted; 'tomato paste' itself has no dedicated canonical row -- "
              "retrieval-only at the grounding layer, unrelated to this rewrite"),
    case("brand_plus_product", "en", "do you have Juhayna milk", "milk",
         brand_text="Juhayna", category_hint="milk"),

    # --- free-from -----------------------------------------------------------
    case("free_from", "en", "chocolate without sugar", "chocolate",
         category_hint="chocolate", free_from="sugar"),
    case("free_from", "ar", "عايز لبن بدون لاكتوز", "لبن",
         category_hint="لبن", free_from="لاكتوز"),

    # --- Arabic --------------------------------------------------------------
    case("arabic", "ar", "عايز جبنة", "جبنة", category_hint="جبنة"),
    case("arabic", "ar", "محتاج حاجة تتغسل بيها الأطباق", "منتج غسيل أطباق",
         category_hint="غسيل أطباق",
         note="indirect description ('something to wash dishes with') rewritten to the plain product"),

    # --- code-switch -----------------------------------------------------------
    case("code_switch", "mixed", "عايز milk من فضلك", "milk", category_hint="milk"),
    case("code_switch", "mixed", "do you have شوكولاتة", "شوكولاتة", category_hint="شوكولاتة"),

    # --- typo cases (the hard "do not touch" rule) ----------------------------
    case("typo", "en", "cucmber", "cucmber", typo_preserved=True,
         category_hint="vegetables", note="user example -- must NOT be silently corrected to 'cucumber'"),
    case("typo", "en", "I want some chiken breast", "chiken breast", typo_preserved=True,
         category_hint="chicken", note="typo preserved in product_query even though the meant "
                                        "product is unambiguous"),
    case("typo", "ar", "عايز بجنة", "بجنة", typo_preserved=True, category_hint="جبنة"),
]


def self_check(cases: list[dict]) -> list[str]:
    """Structural consistency of the CONTRACT itself -- not a test of any
    production code, which does not yet implement this contract."""
    problems = []
    for c in cases:
        if c["typo_preserved"] and c["product_query"] != c["sentence"].strip():
            # product_query is allowed to be a SUBSTRING rewrite once other
            # roles (brand/filler) are removed, but for a typo case with no
            # brand/filler to strip, it must reproduce the input exactly.
            if not (c["brand_text"] or c["free_from"]) and c["product_query"] not in c["sentence"]:
                problems.append(f"{c['sentence']!r}: typo_preserved but product_query "
                                 f"{c['product_query']!r} does not appear in the input")
        if not c["product_query"] and c["tag"] != "off_topic":
            problems.append(f"{c['sentence']!r}: empty product_query")
        if c["category_hint_ambiguous"] and not c["category_hint"]:
            problems.append(f"{c['sentence']!r}: category_hint_ambiguous=True but no category_hint given")
    return problems


def main() -> None:
    problems = self_check(CASES)
    if problems:
        for p in problems:
            print(f"  CONTRACT ERROR: {p}", file=sys.stderr)
        raise SystemExit(f"{len(problems)} contract case(s) inconsistent -- nothing written.")

    tags = sorted({c["tag"] for c in CASES})
    print(f"{len(CASES)} contract cases across {len(tags)} tags: {tags}", file=sys.stderr)

    out = {
        "rules": {
            "product_query": "the shortest clear shopping phrase that preserves the product "
                              "the user intends to buy",
            "may": ["drop filler", "normalize indirect phrasing into the plain product name",
                    "keep a meaningful multi-word concept in the user's own word order"],
            "must_not": ["invent a product/brand/category", "freely correct uncertain spelling",
                         "fold an explicit brand into product_query", "fold free_from into product_query"],
            "category_hint": "the semantic category of the MAIN PRODUCT, not product_query itself; "
                              "a modifying ingredient/flavour/scent/material is not automatically the category",
        },
        "cases": CASES,
    }
    (ROOT / "evaluation" / "sprint6_query_rewrite_contract.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Wrote evaluation/sprint6_query_rewrite_contract.json", file=sys.stderr)


if __name__ == "__main__":
    main()

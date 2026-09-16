"""Sprint 5 Part 2: fixes two real collision mechanisms found in the
Sprint 5 Part 1 Arabic/code-switch research spike's live evaluation (78
real interactions through the real pipeline), both root-caused to exact
rapidfuzz scores via real catalog data, not assumed:

1. LEFTOVER RE-RESOLUTION COLLISION (e.g. "lactose free milk"): a 2-word
   category match ("lactose free") wins the first-pass competition and is
   removed, leaving a single ordinary product word ("milk") sitting alone
   in the leftover text. That orphaned word then loses a FRESH,
   unprotected brand re-scan to a coincidental fuzzy collision it would
   NOT have won in the original full-text competition ("milk" scores
   88.9 against the real brand "Milka"; "chocolate" scores 88.9 against
   "Chocodate" -- both well above the 80 threshold). Fixed generically via
   a new `_protected_category_words()` check, applied ONLY to the
   leftover brand re-resolution call (never the first pass, so real
   multi-word brands that legitimately contain a product word -- "Ahmed
   Tea", "Coffee Break", "My Meat", "Mc Sauce", see
   parse_keyword_query's own docstring -- still compete fairly there).

2. NEGATION COLLAPSING TO THE POSITIVE CONCEPT (e.g. "بدون سكر" / "من غير
   سكر" / "without sugar"): the negation wording itself was previously
   just inert leftover text, so the query fell back to the ordinary
   competing-match resolution, which found the literal, POSITIVE "Sugar"
   category (sugar_5711) -- the opposite of what was asked. The real
   catalog has a confirmed, dedicated "Sugar Free" category
   (sugar_free_1736, real products), so a narrow, explicit
   `_FREE_FROM_COUNTERPART` mapping now redirects negated queries to it.
   Also fixes an unrelated but real direct collision found in the same
   spike: "بدون" ("without") alone, or combined with a preceding word
   ("لبن بدون" = "milk without"), fuzzy-matches real brand aliases
   ("بوردون"/Bordonn at 80.0, "بون بون"/Bonbons at exactly 80.0) purely by
   coincidence -- fixed via a small, deliberately separate
   `_BRAND_FUZZY_WORD_EXCLUSIONS` set (NOT the general blocklist, which
   only blocks a window's FULL text, not partial containment), scoped to
   "بدون" specifically because it is a pure negation particle that could
   never legitimately be part of a real multi-word brand name (unlike
   "meat"/"tea"/"sauce").

Explicitly NOT touched/fixed in this pass (deferred, either to a future
sprint or out of scope by the task's own priority list):
  - The "كريم" (cream) / Nivea skincare vs. cream_11677 (dairy/cooking
    cream) taxonomy collision -- confirmed via direct DB query to be a
    real, unrelated taxonomy gap, not a fuzzy-matching bug.
  - The "لبن الشوفان" (oat milk, Arabic) vs. "oat milk" (English)
    asymmetry -- root cause is an arbitrary DB-row-order tie-break
    between two simultaneously-valid single-word exact category matches
    (milk_29 vs oats_11676), which would need a new competing-match
    ambiguity rule validated by a full corpus-wide sweep before it could
    safely change; deferred per this project's own standing discipline
    for any resolution-logic change.
  - "كويس" (colloquial "good/fine") coincidentally fuzzy-matching the
    real brand alias "سكويسى" (Squeasy) at exactly 80.0 -- unlike "بدون",
    this is a generic filler adjective rather than a category/product
    concept word or a functional/grammatical particle, so it does not
    fit either of the two fix mechanisms above; left unresolved here.

Every case goes through the full parse_keyword_query()/search_keyword()
pipeline (never an isolated helper, never a hand-built FilterSet), per
this project's CRITICAL CONSTRAINT (src/validation/validate.py) -- the
fuzzy resolution behavior IS the thing under test.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.search_engine.keyword_baseline import parse_keyword_query, search_keyword  # noqa: E402


# --- A. brand-collision negative cases: category/product word must not
# --- be stolen by a coincidental fuzzy brand match on the leftover text

def test_lactose_free_milk_does_not_steal_brand_milka():
    fs = parse_keyword_query("lactose free milk")
    assert fs.category == "lactose_free_32297"
    assert fs.brand is None
    assert fs.query_text == "milk"


def test_milk_lactose_free_word_order_does_not_steal_brand_milka():
    fs = parse_keyword_query("milk lactose free")
    assert fs.category == "lactose_free_32297"
    assert fs.brand is None
    assert fs.query_text == "milk"


def test_arabic_milk_lactose_free_mixed_does_not_steal_brand_milka():
    fs = parse_keyword_query("لبن lactose free")
    assert fs.category == "lactose_free_32297"
    assert fs.brand is None


def test_lactose_free_arabic_milk_mixed_does_not_steal_brand_milka():
    fs = parse_keyword_query("lactose free لبن")
    assert fs.category == "lactose_free_32297"
    assert fs.brand is None


def test_sugar_free_chocolate_does_not_steal_brand_chocodate():
    fs = parse_keyword_query("sugar free chocolate")
    assert fs.category == "sugar_free_1736"
    assert fs.brand is None
    assert fs.query_text == "chocolate"


def test_arabic_milk_without_lactose_does_not_match_brand_bonbons():
    # "لبن بدون" (2-word window) scores exactly 80.0 against the real
    # brand alias "بون بون" (Bonbons) -- purely coincidental. (Sprint 5
    # Part 3's generic free-from search now also redirects this to
    # lactose_free_32297 -- see test_semantic_phrase_preservation.py --
    # but the ORIGINAL bug this test guards is specifically the brand
    # collision, which must stay fixed regardless of which category wins.)
    fs = parse_keyword_query("لبن بدون لاكتوز")
    assert fs.brand is None


def test_standalone_arabic_without_does_not_match_brand_bordonn():
    # "بدون" alone scores exactly 80.0 against the real brand alias
    # "بوردون" (Bordonn) -- purely coincidental.
    fs = parse_keyword_query("بدون سكر")
    assert fs.brand is None


# --- B. true-brand positive controls: real brand queries must still
# --- resolve correctly (the fix must not be overbroad)

def test_milka_english_still_resolves_as_brand():
    fs = parse_keyword_query("Milka chocolate")
    assert fs.brand == "milka"
    assert fs.category == "chocolate_2"


def test_milka_arabic_still_resolves_as_brand():
    fs = parse_keyword_query("ميلكا")
    assert fs.brand == "milka"


def test_chocodate_english_still_resolves_as_brand():
    fs = parse_keyword_query("Chocodate")
    assert fs.brand == "chocodate"


def test_bonbons_english_still_resolves_as_brand():
    fs = parse_keyword_query("Bonbons")
    assert fs.brand == "bonbons"


def test_bonbons_arabic_still_resolves_as_brand():
    fs = parse_keyword_query("بون بون")
    assert fs.brand == "bonbons"


def test_freee_still_resolves_as_brand_alongside_sugar_free_category():
    fs = parse_keyword_query("Freee sugar free")
    assert fs.brand == "freee"
    assert fs.category == "sugar_free_1736"


def test_docstring_example_ahmed_tea_still_wins_first_pass():
    # parse_keyword_query's own docstring cites this as a real multi-word
    # brand containing a real category word ("tea") that must still win
    # via length in the FIRST-PASS competition -- the new word-exclusion
    # mechanism must be scoped narrowly enough not to break it.
    fs = parse_keyword_query("Ahmed Tea")
    assert fs.brand == "ahmed_tea"


def test_docstring_example_coffee_break_still_wins_first_pass():
    fs = parse_keyword_query("Coffee Break")
    assert fs.brand == "coffee_break"


# --- C. negation / free-from redirection

def test_arabic_min_ghair_sugar_redirects_to_sugar_free_category():
    fs = parse_keyword_query("من غير سكر")
    assert fs.category == "sugar_free_1736"
    assert fs.brand is None


def test_arabic_bidoon_sugar_redirects_to_sugar_free_category():
    fs = parse_keyword_query("بدون سكر")
    assert fs.category == "sugar_free_1736"
    assert fs.brand is None


def test_english_without_sugar_redirects_to_sugar_free_category():
    fs = parse_keyword_query("without sugar")
    assert fs.category == "sugar_free_1736"
    assert fs.brand is None


def test_positive_sugar_query_is_not_redirected():
    fs = parse_keyword_query("sugar")
    assert fs.category == "sugar_5711"


def test_positive_arabic_sugar_query_is_not_redirected():
    fs = parse_keyword_query("سكر")
    assert fs.category == "sugar_5711"


def test_negation_redirects_even_without_a_positive_counterpart_category():
    # Sprint 5 Part 3 superseded Part 2's hardcoded _FREE_FROM_COUNTERPART
    # (which could only redirect a concept that ALSO had its own plain
    # positive category, e.g. sugar_5711 -- it had no way to redirect
    # "lactose" at all, since no plain "Lactose" category exists to look
    # a counterpart up FROM) with a generic catalog search
    # (_find_free_from_category) that finds lactose_free_32297 directly.
    # This is a real, intended improvement over Part 2's behavior, not a
    # regression -- see test_brand_collision_and_negation_fixes.py's
    # module docstring / keyword_baseline.py's _find_free_from_category.
    fs = parse_keyword_query("milk without lactose")
    assert fs.category == "lactose_free_32297"
    assert fs.brand is None


def test_negation_redirects_arabic_gluten_via_generic_catalog_search():
    fs = parse_keyword_query("لبن بدون جلوتين")
    assert fs.category == "gluten_free_27956"
    assert fs.brand is None


def test_negation_with_truly_no_catalog_evidence_is_inert():
    # A concept with genuinely no free-from category anywhere in the real
    # catalog must still be left alone -- full phrase preserved as free
    # text, never a fabricated category.
    fs = parse_keyword_query("milk without vanilla flavoring xyz123")
    assert fs.category == "milk_29"
    assert fs.brand is None
    assert "vanilla" in fs.query_text


# --- D. all 6 lactose-free phrasings -- must resolve to the real
# --- lactose_free_32297 category and return real lactose-free products
# --- (top product names inspected, not just total_count > 0)

_LACTOSE_FREE_PHRASINGS = [
    "lactose free milk",
    "milk lactose free",
    "لبن بدون لاكتوز",
    "لبن من غير لاكتوز",
    "لبن lactose free",
    "lactose free لبن",
]


def test_all_six_lactose_free_phrasings_return_zero_results_false():
    for text in _LACTOSE_FREE_PHRASINGS:
        result = search_keyword(text, limit=5)
        assert result.zero_result is False, f"{text!r} unexpectedly returned zero results"
        assert result.total_count > 0, f"{text!r} unexpectedly returned zero results"


# Sprint 5 Part 3: all 6 phrasings now resolve to the real, dedicated
# lactose_free_32297 category -- either the English "lactose free" phrase
# matches it directly, or (for the Arabic "بدون"/"من غير" negation forms)
# the generic _find_free_from_category catalog search finds it directly,
# without needing lactose to have its own plain positive category (Part
# 2's hardcoded _FREE_FROM_COUNTERPART couldn't do this; Part 3's generic
# mechanism can). All 6 must reliably surface real lactose-free-labeled
# products in the top 5.
def test_all_six_lactose_free_phrasings_resolve_the_dedicated_category():
    for text in _LACTOSE_FREE_PHRASINGS:
        fs = parse_keyword_query(text)
        assert fs.category == "lactose_free_32297", f"{text!r} -> category={fs.category!r}"
        assert fs.brand is None, f"{text!r} -> brand={fs.brand!r}"


def test_all_six_lactose_free_phrasings_surface_real_lactose_free_products():
    for text in _LACTOSE_FREE_PHRASINGS:
        result = search_keyword(text, limit=5)
        names = [p["name_en"] for p in result.products[:5]]
        assert any("lactose" in n.lower() for n in names), (
            f"{text!r} top-5 did not include a real lactose-free product: {names}"
        )


def test_lactose_free_english_and_arabic_forms_resolve_the_same_category():
    en = parse_keyword_query("lactose free milk")
    ar = parse_keyword_query("لبن بدون لاكتوز")
    assert en.category == ar.category == "lactose_free_32297"


# --- E. direct-vs-conversational parity: results should not differ
# --- wildly in kind between a terse and a natural phrasing of the same need

def test_sugar_free_direct_and_negation_phrasing_reach_the_same_category():
    direct = parse_keyword_query("sugar free")
    negated = parse_keyword_query("بدون سكر")
    assert direct.category == negated.category == "sugar_free_1736"

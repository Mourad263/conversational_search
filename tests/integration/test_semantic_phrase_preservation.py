"""Sprint 5 Part 3: fixes the CORE weakness behind several of Part 2's
remaining gaps -- multi-word semantic concepts ("lactose free", "full fat
milk", negation phrases) being decomposed too early, with individual
leftover words then independently reinterpreted as category/brand/free
text, sometimes destroying the user's intended meaning. Three generic
fixes, none product-specific:

1. _find_free_from_category() (keyword_baseline.py) replaces Part 2's
   hardcoded _FREE_FROM_COUNTERPART dict (POSITIVE-category-slug ->
   free-from-category-slug, one entry per concept -- could only redirect
   a concept that ALSO had its own plain positive category, e.g. sugar,
   and had no way to cover lactose/gluten at all) with a genuine
   catalog-grounded search: does ANY real category name contain a
   free-from marker ("free"/"خالي") AND a word matching the negated
   concept? Only 3 such categories exist catalog-wide (Sugar Free,
   Lactose Free, Gluten Free), so this is a small, safe search, and it
   now correctly covers lactose/gluten negation too, which Part 2 never
   could.

2. Head-position-aware tie-break in _extract_first_phrase_match(): when
   two DIFFERENT real single-word exact category matches tie at the same
   word-length (e.g. "لبن" -> milk and "الشوفان" -> oats both present in
   "لبن الشوفان"), the winner is now the query's linguistic HEAD noun, not
   whichever candidate happened to come first in an arbitrary DB-row-order
   list. A first version always preferred the leftmost match, which
   correctly fixed the Arabic oat-milk asymmetry (Arabic idafa/adjective
   constructions are head-FIRST) but was then PROVEN wrong for English by
   an adversarial follow-up audit: English noun-noun compounds are
   head-LAST ("cream cheese" is a CHEESE, "chocolate milk" is a MILK,
   "milk chocolate" is a CHOCOLATE), and "cream cheese" -- a real, common
   product -- returned ZERO results under always-leftmost (category=
   cream_11677 from leftmost "cream", even though the real product "Kiri
   Cream Cheese" is catalogued under "cheese"). Fixed by making the
   direction depend on the query's language (is_arabic(), already used by
   _normalize_for_fuzzy -- no new language detection added): Arabic
   prefers leftmost, everything else prefers rightmost.

3. _CATEGORY_COMPOUND_ALIASES adds 2 evidence-backed compound-phrase
   aliases ("full fat milk" -> full_cream_milk_31, "low fat milk" ->
   skimmed_milk_39), confirmed via direct corpus lookup (every real
   product titled "... Full Fat Milk ..." is tagged full_cream_milk_31;
   both real "... Low Fat ..." milk-family products are tagged
   skimmed_milk_39) -- NOT a bare "full fat"/"low fat" alias, since both
   terms are also used generically across cheese/meat product titles in
   this same catalog and a bare alias would wrongly redirect those. Also
   fixes a real "fat" (from "low/full fat") vs the unrelated real brand
   "Fast" (85.7 fuzzy score) collision, blocklisted the same way as
   "wafers"/"cookie" already are.

Also fixes a real gap found during this pass's own audit: the negation
branch of parse_keyword_query() never applied the Part 2
protected-category-words safeguard to its own leftover text, so
"شوكولاتة بدون سكر" (chocolate without sugar) redirected correctly to
sugar_free_1736 but then let "شوكولاتة" get stolen by a fuzzy brand match
to the real brand "شوكودات"/Chocodate -- fixed by applying the same
protection there too.

4. (Final adversarial audit) _resolve_negation_free_from() now scans a
   small bounded window of words after the negation marker
   (_FREE_FROM_WINDOW_WORDS = 3), not just the single word immediately
   following it. Real, confirmed bug: "no ADDED sugar" / "without
   ARTIFICIAL sugar" only ever captured the modifier word ("added"/
   "artificial"), found no free-from category for it, and silently gave
   up -- the negation was then dropped entirely and ordinary resolution
   matched the literal, POSITIVE "Sugar" category (sugar_5711), exactly
   the invariant this whole mechanism exists to prevent ("without added
   sugar" even returned ZERO results). Arabic post-nominal adjectives
   ("بدون سكر مضاف") never hit this bug since the noun directly follows
   the marker there -- the asymmetry is a real English-vs-Arabic grammar
   difference, not a coincidence.

Deliberately proven NOT to need a fix by this pass's adversarial audit:
"لبن الشوفان" reversed to "الشوفان لبن" still returns zero results under
the head-position tie-break -- but that reversed order is not
grammatical Arabic (idafa always puts the head noun first), so this is
an honest zero-result on an unnatural input, not a wrong confident
answer, and is NOT treated as a failure requiring a fix.

Deliberately deferred (no real catalog evidence, or explicitly out of
scope -- see the Part 3 final report): Arabic "قليل الدسم" applied to
milk (every real product using that exact phrase in this catalog is
cheese, not milk), the كريم/Nivea cream-taxonomy collision, vague-query
ranking, recommendation UX, response generation, embeddings.

Every case goes through the full parse_keyword_query()/search_keyword()
pipeline (never an isolated helper, never a hand-built FilterSet), per
this project's CRITICAL CONSTRAINT (src/validation/validate.py).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.search_engine.keyword_baseline import parse_keyword_query, search_keyword  # noqa: E402


# --- A. FREE-FROM: generic catalog-grounded resolution, both concepts
# --- that DO and DON'T have their own plain positive category

def test_sugar_free_chocolate_english_direct():
    fs = parse_keyword_query("sugar free chocolate")
    assert fs.category == "sugar_free_1736"
    assert fs.brand is None
    assert fs.query_text == "chocolate"


def test_chocolate_without_sugar_english_negation():
    fs = parse_keyword_query("chocolate without sugar")
    assert fs.category == "sugar_free_1736"
    assert fs.brand is None


def test_arabic_chocolate_without_sugar_negation_and_no_brand_collision():
    # The real gap found during this pass's audit: the negation branch's
    # leftover "شوكولاتة" was being stolen by brand=chocodate before this
    # fix (same class of bug Part 2 fixed for the main branch).
    fs = parse_keyword_query("شوكولاتة بدون سكر")
    assert fs.category == "sugar_free_1736"
    assert fs.brand is None


def test_arabic_chocolate_min_ghair_sugar_negation():
    fs = parse_keyword_query("شوكولاتة من غير سكر")
    assert fs.category == "sugar_free_1736"
    assert fs.brand is None


def test_lactose_negation_now_redirects_generically_english():
    # Part 2 could not do this (no plain "Lactose" category to redirect
    # FROM) -- Part 3's generic catalog search finds lactose_free_32297
    # directly instead.
    fs = parse_keyword_query("milk without lactose")
    assert fs.category == "lactose_free_32297"
    assert fs.brand is None


def test_lactose_negation_now_redirects_generically_arabic_bidoon():
    fs = parse_keyword_query("لبن بدون لاكتوز")
    assert fs.category == "lactose_free_32297"
    assert fs.brand is None


def test_lactose_negation_now_redirects_generically_arabic_min_ghair():
    fs = parse_keyword_query("لبن من غير لاكتوز")
    assert fs.category == "lactose_free_32297"
    assert fs.brand is None


def test_gluten_negation_now_redirects_generically_arabic():
    fs = parse_keyword_query("لبن بدون جلوتين")
    assert fs.category == "gluten_free_27956"
    assert fs.brand is None


def test_no_sugar_operator_variant():
    fs = parse_keyword_query("no sugar")
    assert fs.category == "sugar_free_1736"


def test_free_from_sugar_operator_variant():
    fs = parse_keyword_query("free from sugar")
    assert fs.category == "sugar_free_1736"


def test_negation_with_no_real_catalog_evidence_stays_inert():
    fs = parse_keyword_query("milk without vanilla flavoring xyz123")
    assert fs.category == "milk_29"
    assert fs.brand is None
    assert "vanilla" in fs.query_text


# --- B. POSITIVE CONTROLS: negation logic must not break plain search

def test_positive_sugar_english():
    assert parse_keyword_query("sugar").category == "sugar_5711"


def test_positive_sugar_arabic():
    assert parse_keyword_query("سكر").category == "sugar_5711"


def test_positive_chocolate():
    assert parse_keyword_query("chocolate").category == "chocolate_2"


def test_positive_lactose_free_direct_phrase_unaffected():
    fs = parse_keyword_query("lactose free")
    assert fs.category == "lactose_free_32297"


def test_positive_milk():
    assert parse_keyword_query("milk").category == "milk_29"


# --- C. FAT MODIFIERS: only where real catalog evidence supports them (milk)

def test_low_fat_milk_resolves_to_skimmed_milk_category():
    fs = parse_keyword_query("low fat milk")
    assert fs.category == "skimmed_milk_39"
    assert fs.brand is None
    result = search_keyword("low fat milk", limit=5)
    names = [p["name_en"] for p in result.products[:5]]
    assert any("skimmed" in n.lower() or "low fat" in n.lower() for n in names), names


def test_full_fat_milk_resolves_to_full_cream_milk_category():
    fs = parse_keyword_query("full fat milk")
    assert fs.category == "full_cream_milk_31"
    assert fs.brand is None
    result = search_keyword("full fat milk", limit=5)
    names = [p["name_en"] for p in result.products[:5]]
    assert any("full cream" in n.lower() or "full fat" in n.lower() for n in names), names


def test_arabic_full_cream_milk_already_worked_and_still_does():
    fs = parse_keyword_query("لبن كامل الدسم")
    assert fs.category == "full_cream_milk_31"


def test_bare_full_fat_does_not_hijack_an_unrelated_cheese_query():
    # The compound alias is scoped to "full fat milk" specifically --
    # a cheese query using the same "full fat" wording must NOT be
    # redirected to a milk category (real evidence: "full fat"/"low fat"
    # are also used generically across cheese products in this catalog).
    fs = parse_keyword_query("full fat cheese")
    assert fs.category != "full_cream_milk_31"


def test_arabic_low_fat_milk_has_no_evidence_and_stays_deferred():
    # No real product in this catalog uses "قليل الدسم" for milk (only
    # cheese) -- correctly NOT redirected, left as plain milk + free text.
    fs = parse_keyword_query("لبن قليل الدسم")
    assert fs.category == "milk_29"
    assert fs.brand is None


# --- D. COMPOUND PRODUCT CONCEPTS: oat milk EN/AR parity

def test_oat_milk_english_resolves_milk_with_real_products():
    fs = parse_keyword_query("oat milk")
    assert fs.category == "milk_29"
    result = search_keyword("oat milk", limit=5)
    names = [p["name_en"] for p in result.products[:5]]
    assert any("oat" in n.lower() for n in names), names


def test_oat_milk_arabic_now_resolves_milk_with_real_products():
    # The core Part 3 fix: leftmost-wins tie-break makes "لبن" (leftmost)
    # win over "الشوفان" (oats), reaching category=milk_29 -- the SAME
    # category English "oat milk" reaches -- instead of an arbitrary,
    # DB-row-order-decided category=oats_11676 that returned zero results.
    fs = parse_keyword_query("لبن الشوفان")
    assert fs.category == "milk_29"
    result = search_keyword("لبن الشوفان", limit=5)
    assert result.zero_result is False
    names = [p["name_en"] for p in result.products[:5]]
    assert any("oat" in n.lower() for n in names), names


def test_vegan_milk_english_unaffected():
    fs = parse_keyword_query("vegan milk")
    assert fs.category == "vegan_milk_43"


def test_vegan_milk_arabic_unaffected():
    fs = parse_keyword_query("لبن نباتي")
    assert fs.category == "vegan_milk_43"


# --- E. TRUE BRAND CONTROLS: must still resolve after the tie-break and
# --- free-from generalization changes

def test_milka_still_resolves_as_brand():
    assert parse_keyword_query("Milka chocolate").brand == "milka"


def test_chocodate_still_resolves_as_brand():
    assert parse_keyword_query("Chocodate").brand == "chocodate"


def test_bonbons_still_resolves_as_brand():
    assert parse_keyword_query("Bonbons").brand == "bonbons"


def test_squeasy_still_resolves_as_brand():
    assert parse_keyword_query("Squeasy garlic paste").brand == "squeasy"


def test_ahmed_tea_still_resolves_as_brand():
    assert parse_keyword_query("Ahmed Tea").brand == "ahmed_tea"


def test_coffee_break_still_resolves_as_brand():
    assert parse_keyword_query("Coffee Break").brand == "coffee_break"


# --- F. MULTI-WORD FREE-FROM: a modifier word between the negation
# --- marker and the real negated noun must not defeat the redirect, and
# --- must never let the query degrade into the POSITIVE category

def test_no_added_sugar_does_not_degrade_to_positive_sugar():
    fs = parse_keyword_query("no added sugar")
    assert fs.category == "sugar_free_1736"
    assert fs.category != "sugar_5711"


def test_without_added_sugar_does_not_degrade_to_positive_sugar():
    # The worst form of the bug: this returned ZERO results before the
    # fix (category=sugar_5711, an impossible combination with the
    # leftover "without added" text as a hard filter).
    fs = parse_keyword_query("without added sugar")
    assert fs.category == "sugar_free_1736"
    result = search_keyword("without added sugar", limit=5)
    assert result.zero_result is False
    assert result.total_count > 0


def test_without_artificial_sugar_does_not_degrade_to_positive_sugar():
    fs = parse_keyword_query("without artificial sugar")
    assert fs.category == "sugar_free_1736"


def test_no_added_salt_has_no_evidence_and_stays_inert():
    # No "salt free"/"added salt" category exists in this catalog --
    # confirmed via direct scan -- so this must NOT invent one; the
    # phrase is correctly preserved as free text.
    fs = parse_keyword_query("no added salt")
    assert fs.category is None
    assert fs.query_text == "no added salt"


def test_arabic_bidoon_sugar_madaf_already_worked_and_still_does():
    # Arabic post-nominal adjective order ("بدون سكر مضاف" = "without
    # sugar added") never hit the multi-word bug -- the noun directly
    # follows the marker -- confirmed unaffected by the window widening.
    fs = parse_keyword_query("بدون سكر مضاف")
    assert fs.category == "sugar_free_1736"


# --- G. HEAD-POSITION-AWARE TIE-BREAK: adversarial word-order queries
# --- proving the direction (leftmost for Arabic, rightmost otherwise) is
# --- evidence-backed, not merely a deterministic placeholder

def test_cream_cheese_resolves_to_cheese_not_cream():
    # The real bug that proved always-leftmost was wrong for English:
    # "cream cheese" is a real, common product (Kiri Cream Cheese, real
    # catalog evidence) but always-leftmost gave category=cream_11677
    # (zero real cream-cheese products) since "cream" is the first word.
    fs = parse_keyword_query("cream cheese")
    assert fs.category == "cheese"
    result = search_keyword("cream cheese", limit=5)
    assert result.zero_result is False
    names = [p["name_en"] for p in result.products[:5]]
    assert any("cream cheese" in n.lower() for n in names), names


def test_milk_chocolate_resolves_to_chocolate_not_milk():
    # "milk chocolate" is a TYPE OF CHOCOLATE (head noun = chocolate,
    # last word) -- English compounds are right-headed.
    fs = parse_keyword_query("milk chocolate")
    assert fs.category == "chocolate_2"


def test_chocolate_milk_resolves_to_milk_not_chocolate():
    # "chocolate milk" is a MILK BEVERAGE (head noun = milk, last word) --
    # the exact opposite category from "milk chocolate" above, proving the
    # tie-break tracks real word order, not a fixed preference either way.
    fs = parse_keyword_query("chocolate milk")
    assert fs.category == "milk_29"
    result = search_keyword("chocolate milk", limit=5)
    names = [p["name_en"] for p in result.products[:5]]
    assert any("chocolate milk" in n.lower() for n in names), names


def test_arabic_oat_milk_still_prefers_leftmost_head_first():
    # Arabic idafa is head-FIRST -- must still prefer leftmost, opposite
    # of the English rule above, proving the direction is language-aware
    # and not simply flipped globally.
    fs = parse_keyword_query("لبن الشوفان")
    assert fs.category == "milk_29"


# --- H. Dietary acceptance matrix (task-required): real search path,
# --- real top-result relevance, for every phrasing of the two core
# --- dietary constraints -- an ordinary non-compliant product is never
# --- treated as an acceptable match, and total_count > 0 alone is never
# --- treated as sufficient evidence of relevance.

_LACTOSE_FREE_DIETARY_PHRASES = [
    "lactose free milk",
    "milk without lactose",
    "لبن بدون لاكتوز",
    "لبن من غير لاكتوز",
]

_SUGAR_FREE_DIETARY_PHRASES = [
    "sugar free chocolate",
    "chocolate without sugar",
    "شوكولاتة بدون سكر",
    "شوكولاتة من غير سكر",
]


def test_lactose_free_dietary_phrases_resolve_the_dedicated_category():
    for text in _LACTOSE_FREE_DIETARY_PHRASES:
        fs = parse_keyword_query(text)
        assert fs.category == "lactose_free_32297", f"{text!r} -> category={fs.category!r}"


def test_lactose_free_dietary_phrases_top_results_are_actually_lactose_free():
    for text in _LACTOSE_FREE_DIETARY_PHRASES:
        result = search_keyword(text, limit=5)
        assert result.zero_result is False, f"{text!r} returned zero results"
        names = [p["name_en"] for p in result.products[:5]]
        assert all("lactose" in n.lower() for n in names), (
            f"{text!r} top-5 included a non-lactose-free product: {names}"
        )


def test_sugar_free_dietary_phrases_resolve_the_dedicated_category():
    for text in _SUGAR_FREE_DIETARY_PHRASES:
        fs = parse_keyword_query(text)
        assert fs.category == "sugar_free_1736", f"{text!r} -> category={fs.category!r}"
        assert fs.brand is None, f"{text!r} -> brand={fs.brand!r} (should not be stolen)"


def test_sugar_free_dietary_phrases_top_results_are_not_ordinary_sugared_products():
    # A real, ordinary sugared chocolate/candy in the top-5 (no sugar-free
    # or no-added-sugar signal in its own name) would be an unacceptable
    # false success for an explicit "sugar free" request.
    no_sugar_signals = ("sugar free", "sugar-free", "no added sugar", "no sugar",
                         "without sugar", "zero sugar", "no calorie")
    for text in _SUGAR_FREE_DIETARY_PHRASES:
        result = search_keyword(text, limit=5)
        assert result.zero_result is False, f"{text!r} returned zero results"
        names = [p["name_en"] for p in result.products[:5]]
        assert all(
            any(signal in n.lower() for signal in no_sugar_signals)
            for n in names
        ), f"{text!r} top-5 included a product with no sugar-free signal: {names}"

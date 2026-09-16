"""Sprint 6: fixes weak fuzzy brand/category matches hijacking ordinary,
real product language that has strong exact evidence in the catalog.
Two distinct mechanisms, found via fresh-session manual testing (not
conversation history, not caused by prior turns):

1. A coincidental FUZZY match beating real product-corpus evidence in the
   first-pass category/brand competition:
     - "paste" (69 real products: Tomato Paste) scores exactly 80.0
       against the unrelated category "Pasta".
     - "peas" (46 real products) scores 88.9 against the unrelated real
       brand "Pears".
     - "frozen peas" (12 real products contain both words) scores 81.8
       against the unrelated category "Frozen Meat" purely because both
       phrases share the word "frozen".
   Fixed inside the shared _fuzzy_phrase_match(): a window is now held to
   the existing protected_threshold (95) when it has strong real
   product-corpus co-occurrence support (_MIN_PRODUCT_COOCCURRENCE_
   SUPPORT=10) AND that support does not substantially overlap the
   specific candidate's own real product membership
   (_MIN_CANDIDATE_OVERLAP_RATIO=0.1, computed from the DB's
   authoritative product.brand_normalized / product_category tables).

2. An EXACT brand match fragmenting a longer, more-specific real product
   phrase during LEFTOVER re-resolution (score-based protection can't
   touch this, since the match is already 100.0, not a fuzzy coincidence):
     - "extra virgin olive oil": category correctly consumes "oil"
       (exact, 1 word) in the first pass; in the leftover-brand step,
       "extra" is an EXACT match to the real brand "Extra", but 73 real
       products contain "extra"+"virgin"+"olive" together -- a strictly
       longer, more specific real phrase than the 1-word brand match.
   Fixed via _longest_evidenced_phrase_window() + _resolve_leftover_
   brand(): the same "more of the query covered wins" principle already
   used elsewhere in this file, applied against real corpus evidence
   instead of another category/brand candidate.

Neither fix is a word-specific mapping or blocklist entry -- grep this
file's own production counterpart (src/search_engine/keyword_baseline.py)
and none of "paste"/"peas"/"frozen peas"/"extra"/"بلدي"/"كراميل"/"رمان"/
"read"/"الوادي" appear there. A small development collision sweep (300
real corpus words vs every brand/category) found the mechanism also
catches several previously-unknown real collisions beyond the 4
originally reported, included below as a representative regression set:
"بلدي"/"balady" (a real, common Arabic/transliterated word for "local/
traditional", found on real Balady-labeled meat and dairy products) vs
the real brand "Lady"; "كراميل" (caramel, real Solo/Monin/Dobella syrup
and sauce products) vs the real brand "Camay"; "رمان" (pomegranate, real
juice/debis products) vs the real brand "Herman"; "read" (real "Read And
Coloring" children's book products) vs the real category "Bread".

A follow-up catalog-scale audit (~6,500 automatically-generated fuzzy
collision pairs, 70/30 dev/holdout split) found _MIN_PRODUCT_
COOCCURRENCE_SUPPORT=10 was itself too permissive: sweeping it against
the pairs the rule is meant to catch showed false-hijack count falling
from 506 (at 10) to 1 (at 3), with zero change in genuine-match recovery
either way -- lowered to 3, the lowest value the dataset actually
covers. This ALSO fixed a real, pre-existing (accepted-as-a-known-quirk)
case: "choclate milk" used to resolve brand="chocodate" (see
tests/integration/test_typo_tolerance_audit.py, now updated) --
"choclate" has 5 real supporting products but ~0 overlap with
Chocodate's own real products, the same false-collision shape as
paste/Pasta, just below the old threshold of 10. "الوادي" (a common
Arabic word for "valley/oasis", real "Wadi Dates" products) vs the real
brand "El Bawadi" is one additional representative case newly caught by
the lowered threshold specifically (support=5, previously unprotected).

Every case goes through the full parse_keyword_query()/search_keyword()
pipeline (never an isolated fuzzy helper, never a hand-built FilterSet),
per this project's CRITICAL CONSTRAINT (src/validation/validate.py) --
the fuzzy resolution behavior IS the thing under test.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.search_engine.keyword_baseline import parse_keyword_query, search_keyword  # noqa: E402


# --- 1. tomato paste from Heinz: must not be hijacked into Pasta, must
# --- preserve the real brand, must return real tomato-paste products

def test_tomato_paste_from_heinz_does_not_resolve_to_pasta_category():
    fs = parse_keyword_query("tomato paste from Heinz")
    assert fs.category != "pasta_5699"
    assert fs.brand == "heinz"


def test_tomato_paste_from_heinz_returns_relevant_heinz_products():
    result = search_keyword("tomato paste from Heinz", limit=5)
    assert result.zero_result is False
    names = [p["name_en"].lower() for p in result.products[:5]]
    assert any("heinz" in n for n in names), names
    assert any("paste" in n or "tomato" in n for n in names), names


def test_bare_paste_does_not_resolve_to_pasta_category():
    fs = parse_keyword_query("paste")
    assert fs.category != "pasta_5699"


def test_bare_paste_returns_real_tomato_paste_products():
    result = search_keyword("paste", limit=5)
    assert result.zero_result is False
    names = [p["name_en"].lower() for p in result.products[:5]]
    assert any("paste" in n for n in names), names


# --- 2. peas: must not be hijacked by the real brand "Pears", must
# --- return real pea products

def test_peas_does_not_resolve_brand_pears():
    fs = parse_keyword_query("peas")
    assert fs.brand != "pears"


def test_peas_returns_real_pea_products():
    result = search_keyword("peas", limit=5)
    assert result.zero_result is False
    names = [p["name_en"].lower() for p in result.products[:5]]
    assert any("pea" in n for n in names), names
    assert not any("pears" in n for n in names), names


# --- 3. frozen peas: must not be hijacked into Frozen Meat/Frozen Beef,
# --- must return real frozen-pea products

def test_frozen_peas_does_not_resolve_to_frozen_meat_category():
    fs = parse_keyword_query("frozen peas")
    assert fs.category not in ("frozen_meat", "frozen_beef_10484")


def test_frozen_peas_returns_real_frozen_pea_products():
    result = search_keyword("frozen peas", limit=5)
    assert result.zero_result is False
    names = [p["name_en"].lower() for p in result.products[:5]]
    assert all("beef" not in n and "burger" not in n and "sausage" not in n for n in names), names
    assert any("pea" in n for n in names), names


# --- 4. extra virgin olive oil: must not be hijacked by the real brand
# --- "Extra", must preserve the olive-oil category, must return real
# --- extra-virgin olive-oil products

def test_extra_virgin_olive_oil_does_not_resolve_brand_extra():
    fs = parse_keyword_query("extra virgin olive oil")
    assert fs.brand != "extra"
    assert fs.category == "oil_5685"


def test_extra_virgin_olive_oil_returns_relevant_products():
    result = search_keyword("extra virgin olive oil", limit=5)
    assert result.zero_result is False
    names = [p["name_en"].lower() for p in result.products[:5]]
    assert any("olive" in n for n in names), names
    assert any("virgin" in n for n in names), names


# --- 5. Representative regression set: newly-discovered generic
# --- collisions from the Sprint 6 diagnostic sweep -- none of these
# --- words are blocklisted or mapped anywhere in production code; the
# --- generic corpus-evidence mechanism protects them the same way

def test_arabic_balady_not_hijacked_by_brand_lady():
    fs = parse_keyword_query("بلدي")  # بلدي
    assert fs.brand != "lady"
    result = search_keyword("بلدي", limit=5)
    assert result.zero_result is False


def test_latin_balady_not_hijacked_by_brand_lady():
    fs = parse_keyword_query("balady")
    assert fs.brand != "lady"
    result = search_keyword("balady", limit=5)
    assert result.zero_result is False
    names = [p["name_en"].lower() for p in result.products[:5]]
    assert any("balady" in n or "bali" in n for n in names), names


def test_arabic_alwadi_not_hijacked_by_brand_el_bawadi():
    # Newly caught specifically by lowering _MIN_PRODUCT_COOCCURRENCE_
    # SUPPORT from 10 to 3 (support=5, previously below the old bar) --
    # a catalog-scale audit found the old value of 10 let hundreds of
    # similar low-but-real-support false collisions through.
    fs = parse_keyword_query("الوادي")  # الوادي
    assert fs.brand != "el_bawadi"
    result = search_keyword("الوادي", limit=5)
    assert result.zero_result is False


def test_arabic_caramel_not_hijacked_by_brand_camay():
    fs = parse_keyword_query("كراميل")  # كراميل
    assert fs.brand != "camay"
    result = search_keyword("كراميل", limit=5)
    assert result.zero_result is False
    names = [p["name_en"].lower() for p in result.products[:5]]
    assert any("caramel" in n for n in names), names


def test_arabic_pomegranate_not_hijacked_by_brand_herman():
    fs = parse_keyword_query("رمان")  # رمان
    assert fs.brand != "herman"
    result = search_keyword("رمان", limit=5)
    assert result.zero_result is False
    names = [p["name_en"].lower() for p in result.products[:5]]
    assert any("pomegranate" in n for n in names), names


def test_read_not_hijacked_by_category_bread():
    fs = parse_keyword_query("read")
    assert fs.category != "bread"
    result = search_keyword("read", limit=5)
    assert result.zero_result is False


# --- 6. True-entity positive controls: the fix must not have weakened
# --- any of the real brands/categories it interacts with

def test_pears_brand_still_resolves():
    fs = parse_keyword_query("Pears")
    assert fs.brand == "pears"
    result = search_keyword("Pears", limit=5)
    names = [p["name_en"].lower() for p in result.products[:5]]
    assert any("pears" in n for n in names), names


def test_extra_brand_still_resolves():
    fs = parse_keyword_query("Extra")
    assert fs.brand == "extra"
    result = search_keyword("Extra", limit=5)
    names = [p["name_en"].lower() for p in result.products[:5]]
    assert any("extra" in n for n in names), names


def test_lady_brand_still_resolves():
    fs = parse_keyword_query("Lady")
    assert fs.brand == "lady"


def test_camay_brand_still_resolves():
    fs = parse_keyword_query("Camay")
    assert fs.brand == "camay"
    result = search_keyword("Camay", limit=5)
    names = [p["name_en"].lower() for p in result.products[:5]]
    assert any("camay" in n for n in names), names


def test_herman_brand_still_resolves():
    fs = parse_keyword_query("Herman")
    assert fs.brand == "herman"
    result = search_keyword("Herman", limit=5)
    names = [p["name_en"].lower() for p in result.products[:5]]
    assert any("herman" in n for n in names), names


def test_bread_category_still_resolves():
    fs = parse_keyword_query("Bread")
    assert fs.category == "bread"
    result = search_keyword("Bread", limit=5)
    names = [p["name_en"].lower() for p in result.products[:5]]
    assert any("bread" in n for n in names), names


def test_milka_brand_still_resolves():
    fs = parse_keyword_query("Milka")
    assert fs.brand == "milka"


def test_ahmed_tea_brand_still_resolves():
    fs = parse_keyword_query("Ahmed Tea")
    assert fs.brand == "ahmed_tea"
    result = search_keyword("Ahmed Tea", limit=5)
    names = [p["name_en"].lower() for p in result.products[:5]]
    assert any("tea" in n for n in names), names

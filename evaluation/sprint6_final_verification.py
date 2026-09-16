"""Final compact-prompt verification -- combined small controlled set.
Real Groq calls, run once. Evaluation-only."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.understanding.llm import understand  # noqa: E402

CASES = [
    # --- 2. زود/ضيف: exact original test_llm.py CASES (bare, no history) ---
    ("zod1_bare", "ضيف عليها جبنة روملي", None, {"intent": "add_filter"}),
    ("zod2_bare", "كمان لو سمحت زود زبادي", None, {"intent": "add_filter"}),
    ("zod3_bare_crossdept", "كمان لو ينفع زودلي شامبو نوع Dove", None, {"intent": "add_filter"}),
    # same but WITH realistic history (the referent "ضيف عليها" naturally needs)
    ("zod1_hist", "ضيف عليها جبنة روملي", ["عايز جبنة"], {"intent": "add_filter"}),
    ("zod2_hist", "كمان لو سمحت زود زبادي", ["عايز لبن"], {"intent": "add_filter"}),
    ("zod3_hist_crossdept", "كمان لو ينفع زودلي شامبو نوع Dove", ["عايز لبن"], {"intent": "add_filter"}),
    # natural additional زود/ضيف same-topic vs a genuine different-topic control
    ("zod_same_topic", "زود براند جهينة كمان", ["عايز لبن تحت خمسين"], {"intent": "add_filter"}),
    ("zod_should_stay_search", "زود عليها منظف بدل اللبن", ["عايز لبن"], {"intent": "search"}),

    # --- 3. query rewrite ---
    ("qr_en_filler", "I need to buy some oat milk please", None,
     {"raw_query_text": lambda r: r and "oat" in r.lower() and "milk" in r.lower() and "please" not in r.lower()}),
    ("qr_en_typo", "I need chiken breast", None,
     {"raw_query_text": lambda r: r and "chicken breast" in r.lower()}),
    ("qr_free_from", "I need milk without lactoze", None,
     {"raw_query_text": lambda r: r and "milk" in r.lower(),
      "free_from": lambda f: f and "lactos" in f.lower()}),
    ("qr_brand_excluded", "show me Juhayna milk", None,
     {"raw_query_text": lambda r: r is None or "juhayna" not in r.lower(),
      "brand_text": lambda b: b and "juhayna" in b.lower()}),
    ("qr_nonsense", "I need something called zrqltnonexistent", None,
     {"raw_query_text": lambda r: r and "zrqlt" in r.lower()}),
    ("qr_ar_multiword", "عايز جبنة قريش طازة", None,
     {"raw_query_text": lambda r: r and "جبنة" in r}),
    ("qr_codeswitch", "عايز oat milk من فضلك", None,
     {"raw_query_text": lambda r: r and "oat" in r.lower() and "milk" in r.lower()}),

    # --- 4. category specificity (unseen) ---
    ("cat_specific_1", "do you have detergent?", None,
     {"category_hint": lambda c: c and "detergent" in c.lower()}),
    ("cat_broad_1", "show me your cleaning supplies", None,
     {"category_hint": lambda c: c and ("cleaning" in c.lower())}),
    ("cat_specific_ar", "عايز عسل", None,
     {"category_hint": lambda c: c is not None}),

    # --- 5. topic switch (unseen) ---
    ("switch_en", "forget it, I need soap instead", ["I need rice"], {"intent": "search"}),
    ("continuation_en", "make it the low-fat version instead", ["I need milk"],
     {"intent": lambda i: i in ("modify_filter", "add_filter")}),
    ("switch_codeswitch", "خلاص، I need توست instead", ["عايز لبن"], {"intent": "search"}),

    # --- 6. Task 3B recommendation routing ---
    ("rec_milk", "what milk do you recommend?", None,
     {"intent": lambda i: i != "no_op", "recommendation_request": True}),
    ("rec_show_more", "show me more", ["I need shampoo"], {"recommendation_request": True}),
    ("rec_anything_else", "anything else?", ["I need milk"], {"recommendation_request": True}),
    ("rec_ar_more", "وريني أكتر", ["عايز شاي"], {"recommendation_request": True}),
    ("rec_ar_alt", "فيه بدائل؟", ["عايز جبنة"], {"recommendation_request": True}),
    ("rec_neg_1", "I need milk", None, {"recommendation_request": False}),
    ("rec_neg_2", "change the price to under 50", ["I need milk"], {"recommendation_request": False}),

    # --- 8. off-topic ---
    ("offtopic_en", "what's the weather today?", None, {"intent": "off_topic"}),
]

results = []
for label, text, history, checks in CASES:
    a = understand(text, history=history)
    row = {"label": label, "text": text}
    ok = True
    for attr, expected in checks.items():
        actual = getattr(a, attr)
        actual_v = actual.value if attr == "intent" else actual
        passed = expected(actual_v) if callable(expected) else (actual_v == expected)
        row[attr] = actual_v
        row[f"{attr}_pass"] = passed
        ok = ok and passed
    row["pass"] = ok
    results.append(row)
    print(f"{label}: {row} {'OK' if ok else 'FAIL'}", file=sys.stderr)

n_pass = sum(r["pass"] for r in results)
print(f"\nFINAL VERIFICATION: {n_pass}/{len(results)} passed", file=sys.stderr)

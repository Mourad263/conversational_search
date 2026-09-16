"""Semantic regression remediation DEV set -- category-hint specificity +
topic-switch/continuation, plus Task 3B recommendation-routing controls
(must not regress). Evaluation-only, real Groq calls, small controlled set.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.understanding.llm import understand  # noqa: E402

# (label, text, history, checks: dict of attr->expected or callable)
CASES = [
    # A. specific category should remain specific
    ("A_juice", "I want some juice", None, {"category_hint": lambda c: c and "juice" in c.lower() and "beverage" not in c.lower()}),
    ("A_diapers", "عايز حفاضات", None, {"category_hint": lambda c: c is not None and "حفاض" in c}),
    # B. intentionally broad category should remain broad
    ("B_beverages", "show me your beverages", None, {"category_hint": lambda c: c and "beverage" in c.lower()}),
    # C. same-topic replacement
    ("C_skimmed", "make it skimmed milk instead", ["I need milk"], {"intent": "modify_filter"}),
    ("C_brand", "Juhayna instead", ["I need milk"], {"intent": "modify_filter"}),
    # D. different-topic replacement
    ("D_detergent", "I need detergent", ["I need milk"], {"intent": "search"}),
    # E. different-topic replacement using "instead"
    ("E_detergent_instead", "detergent instead", ["I need milk"], {"intent": "search"}),
    ("E_rice_instead_ar", "لا، عايز رز بدل كده", ["عايز شامبو"], {"intent": "search"}),
    # F. Arabic same-topic continuation
    ("F_ar_continuation", "خليها تحت خمسين", ["عايز لبن"], {"intent": "modify_filter"}),
    # G. Arabic topic switch
    ("G_ar_switch", "لأ عايز منظف بدل كده", ["عايز لبن"], {"intent": "search"}),
    # H. code-switch topic switch
    ("H_codeswitch_switch", "actually عايز rice بدل كده", ["I need shampoo"], {"intent": "search"}),
    # I. Task 3B recommendation routing controls (must not regress)
    ("I_rec_milk", "what milk do you recommend?", None, {"recommendation_request": True}),
    ("I_show_more", "show me more", ["I need shampoo"], {"recommendation_request": True}),
    ("I_anything_else", "anything else?", ["I need milk"], {"recommendation_request": True}),
    ("I_neg_search", "I need milk", None, {"recommendation_request": False}),
    ("I_neg_price", "change the price to under 50", ["I need milk"], {"recommendation_request": False}),
]

results = []
for label, text, history, checks in CASES:
    a = understand(text, history=history)
    row = {"label": label, "text": text}
    ok = True
    for attr, expected in checks.items():
        actual = getattr(a, attr)
        if attr == "intent":
            actual_v = actual.value
        else:
            actual_v = actual
        passed = expected(actual_v) if callable(expected) else (actual_v == expected)
        row[attr] = actual_v
        row[f"{attr}_pass"] = passed
        ok = ok and passed
    row["pass"] = ok
    results.append(row)
    print(f"{label}: {row} {'OK' if ok else 'FAIL'}", file=sys.stderr)

n_pass = sum(r["pass"] for r in results)
print(f"\nDEV: {n_pass}/{len(results)} passed", file=sys.stderr)

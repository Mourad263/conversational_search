"""Semantic regression remediation HOLDOUT -- unseen wording, run once.
Tests the GENERAL rules (category specificity, topic-switch judgment), not
memorization of the DEV set or the two prompt anchor examples."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.understanding.llm import understand  # noqa: E402

CASES = [
    # specific-vs-broad category, unseen wording
    ("specific_1", "do you have any coffee?", None,
     {"category_hint": lambda c: c and "coffee" in c.lower()}),
    ("specific_2", "عايزة شاي", None,
     {"category_hint": lambda c: c is not None and ("شاي" in c or "tea" in c.lower())}),
    ("broad_1", "what personal care products do you sell?", None,
     {"category_hint": lambda c: c and "personal care" in c.lower()}),
    # same-topic continuations, unseen wording
    ("continuation_en", "actually get me the full-fat version", ["I need milk"],
     {"intent": lambda i: i in ("modify_filter", "add_filter")}),
    ("continuation_ar", "خليها من نوع المراعي", ["عايز لبن"],
     {"intent": lambda i: i in ("modify_filter", "add_filter")}),
    # unrelated topic switches, unseen wording
    ("switch_en_1", "forget that, I need toothpaste", ["I want yogurt"], {"intent": "search"}),
    ("switch_en_2", "never mind, switch me to rice instead", ["I need chicken"], {"intent": "search"}),
    ("switch_ar_1", "بلاش كده، عايز صابون", ["عايز جبنة"], {"intent": "search"}),
    ("switch_codeswitch", "خلاص سيبك من ده، I want بسكويت instead", ["I need tea"], {"intent": "search"}),
    # Task 3B controls, unseen wording
    ("rec_control_1", "any suggestions for a good snack?", None, {"recommendation_request": True}),
    ("rec_control_2", "عندك حاجة تانية تنصحيني بيها؟", ["عايز شامبو"], {"recommendation_request": True}),
    ("rec_control_neg", "I need two bottles of water", None, {"recommendation_request": False}),
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
print(f"\nHOLDOUT: {n_pass}/{len(results)} passed", file=sys.stderr)

"""Task 3B HOLDOUT -- unseen phrasings, run once, not used to tune the
prompt. Different wording than the DEV set and than the prompt's own
inline anchors ("show me more"/"وريني أكتر" -- neither reused here)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.understanding.llm import understand  # noqa: E402

CASES = [
    # A. English direct recommendation
    ("A_en_direct_1", "give me alternatives", None, True),
    ("A_en_direct_2", "suggest something similar", None, True),
    # B. English follow-up exploration
    ("B_en_followup_1", "what else do you have?", ["I need chocolate"], True),
    ("B_en_followup_2", "can you recommend another one?", ["I want yogurt"], True),
    # C. English "show me more" variants (not the literal prompt anchor phrase)
    ("C_en_more_1", "got anything else to offer?", ["I need shampoo"], True),
    # D. Arabic direct recommendation
    ("D_ar_direct_1", "رشحلي حاجة", None, True),
    ("D_ar_direct_2", "عندك بدائل؟", None, True),
    # E. Egyptian Arabic follow-up
    ("E_egy_followup_1", "فيه اختيارات تانية؟", ["عايز شاي"], True),
    ("E_egy_followup_2", "هاتلي حاجة شبه دي", ["عايز جبنة"], True),
    # F. Arabic "show me more" variant (not the literal prompt anchor phrase)
    ("F_ar_more_1", "إيه تاني عندك؟", ["عايز عصير"], True),
    # G. code-switch
    ("G_codeswitch_1", "show me حاجات تانية", ["عايز شامبو"], True),
    ("G_codeswitch_2", "ممكن suggest حاجة شبه دي", ["I need coffee"], True),
    # H. same-turn product + recommendation
    ("H_same_turn_1", "suggest some good chocolate", None, True),
    ("H_same_turn_2", "ممكن ترشحلي حاجة تانية زي اللبن ده؟", None, True),
    # I. recommendation with existing state (explicit)
    ("I_with_state_1", "what else?", ["lactose-free milk"], True),
    # J. recommendation with no state
    ("J_no_state_1", "ممكن ترشحلي حاجة؟", None, True),
    # K. ordinary search negative controls
    ("K_neg_1", "I want yogurt", None, False),
    ("K_neg_2", "عايز شاي", None, False),
    ("K_neg_3", "show me Juhayna milk", None, False),
    # L. filter-modification negative controls
    ("L_neg_1", "make it under 100", ["I need milk"], False),
    ("L_neg_2", "actually I want chicken instead", ["I need beef"], False),
    # M. off-topic negative controls
    ("M_neg_1", "tell me a joke", None, False),
]

results = []
mismatches = []
for label, text, history, expected in CASES:
    a = understand(text, history=history)
    ok = a.recommendation_request == expected
    results.append({
        "label": label, "text": text, "history": history,
        "expected_recommendation_request": expected,
        "actual_recommendation_request": a.recommendation_request,
        "intent": a.intent.value, "pass": ok,
    })
    if not ok:
        mismatches.append(label)
    print(f"{label}: expected={expected} actual={a.recommendation_request} "
          f"intent={a.intent.value} {'OK' if ok else 'MISMATCH'}", file=sys.stderr)

n = len(results)
passed = n - len(mismatches)
print(f"\nHOLDOUT: {passed}/{n} passed. Mismatches: {mismatches}", file=sys.stderr)

Path("evaluation/sprint6_task3b_holdout_results.json").write_text(
    json.dumps({"n": n, "passed": passed, "mismatches": mismatches, "results": results},
               ensure_ascii=False, indent=2), encoding="utf-8")

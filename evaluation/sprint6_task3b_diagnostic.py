"""Task 3B diagnostic pass -- checks the CURRENT (compressed) SYSTEM_PROMPT's
recommendation_request behavior before any change. Evaluation-only, one
small controlled set, real Groq calls (throttled by being small)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.understanding.llm import understand  # noqa: E402

CASES = [
    ("A_en_direct", "recommend something", None),
    ("B_en_followup", "show me some other options", ["I need shampoo"]),
    ("C_en_show_more", "show me more", ["I need shampoo"]),
    ("D_ar_direct", "افترح عليا حاجة", None),
    ("E_egy_followup", "وريني حاجات تانية", ["عايز شامبو"]),
    ("F_ar_show_more", "وريني أكتر", ["عايز شامبو"]),
    ("G_codeswitch", "recommendلي حاجة تانية", ["عايز شامبو"]),
    ("H_same_turn", "what milk do you recommend?", None),
    ("I_with_state", "anything else?", ["I need milk"]),
    ("J_no_state", "what do you recommend?", None),
    ("K_neg_search", "I need milk", None),
    ("L_neg_filter", "change the price to under 50", ["I need milk"]),
    ("M_neg_offtopic", "what's the weather?", None),
]

results = []
for label, text, history in CASES:
    a = understand(text, history=history)
    results.append({
        "label": label, "text": text, "history": history,
        "intent": a.intent.value, "recommendation_request": a.recommendation_request,
        "raw_query_text": a.raw_query_text, "category_hint": a.category_hint,
    })
    print(f"{label}: intent={a.intent.value} rec_req={a.recommendation_request} "
          f"raw={a.raw_query_text!r}", file=sys.stderr)

Path("evaluation/sprint6_task3b_diagnostic_results.json").write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.understanding.llm import understand  # noqa: E402

CASES = [
    ("H_milk_1", "what milk do you recommend?", None),
    ("H_milk_2", "what milk do you recommend?", None),
    ("H_choc_1", "suggest some good chocolate", None),
    ("H_choc_2", "suggest some good chocolate", None),
    ("H_ar_1", "ممكن ترشحلي حاجة تانية زي اللبن ده؟", None),
    # re-verify pure no_op / show-me-more / negatives still correct
    ("A_pure", "recommend something", None),
    ("C_show_more", "show me more", ["I need shampoo"]),
    ("K_neg", "I need milk", None),
]

for label, text, history in CASES:
    a = understand(text, history=history)
    print(f"{label}: intent={a.intent.value} rec_req={a.recommendation_request} "
          f"raw={a.raw_query_text!r} cat={a.category_hint!r}", file=sys.stderr)

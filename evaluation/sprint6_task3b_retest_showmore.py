import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.understanding.llm import understand  # noqa: E402

CASES = [
    ("C_en_show_more_1", "show me more", ["I need shampoo"]),
    ("C_en_show_more_2", "show me more", ["I need shampoo"]),
    ("C_en_show_more_3", "show me more", ["I need shampoo"]),
    ("F_ar_show_more_recheck", "وريني أكتر", ["عايز شامبو"]),
]

for label, text, history in CASES:
    a = understand(text, history=history)
    print(f"{label}: intent={a.intent.value} rec_req={a.recommendation_request}", file=sys.stderr)

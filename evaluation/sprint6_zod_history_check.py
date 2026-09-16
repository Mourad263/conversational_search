import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.understanding.llm import understand  # noqa: E402

CASES = [
    ("1a_no_history", "ضيف عليها جبنة روملي", None),
    ("1b_with_history", "ضيف عليها جبنة روملي", ["عايز جبنة"]),
    ("2a_no_history", "كمان لو سمحت زود زبادي", None),
    ("2b_with_history", "كمان لو سمحت زود زبادي", ["عايز لبن"]),
    ("3_cross_topic_control", "زود عليها منظف كمان", ["عايز لبن"]),
]

for label, text, history in CASES:
    a = understand(text, history=history)
    print(f"{label}: intent={a.intent.value} raw_query_text={a.raw_query_text!r} "
          f"category_hint={a.category_hint!r}", file=sys.stderr)

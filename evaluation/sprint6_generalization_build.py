"""Sprint 6 catalog-scale generalization audit: builds the automated
fuzzy-collision dataset (Step 1) and the frozen dev/holdout split
(Step 2). Evaluation script only -- imports production code read-only
(reuses the SAME corpus-evidence primitives keyword_baseline.py itself
uses: _corpus_cooccurrence_ids, product_ids_by_brand_slug,
product_ids_by_category_slug -- per this project's "reuse existing
structures" rule), never modifies it.

Usage: python evaluation/sprint6_generalization_build.py
Writes:
  evaluation/sprint6_generalization_dataset.json   (full dataset, both splits)
  evaluation/sprint6_generalization_holdout.json   (holdout only, frozen)
  evaluation/sprint6_generalization_holdout.sha256.txt
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rapidfuzz import fuzz, process  # noqa: E402
from src.ingestion.text_normalize import is_arabic  # noqa: E402
from src.search_engine import keyword_baseline as kb  # noqa: E402
from src.search_engine.index import get_index  # noqa: E402
from src.search_engine.tokenizer import tokenize  # noqa: E402

SEED = 20260914
SCORE_FLOOR = 70.0  # below the real 80 operating threshold, deliberately,
# so the dataset also covers the near-miss zone needed for Step 6/7's
# threshold-boundary analysis -- not just already-triggering collisions.
MIN_WORD_SUPPORT = 3
MAX_PHRASE_SOURCES = 6000  # bound phrase-pair generation to a tractable size


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def main() -> None:
    idx = get_index()
    catalog = kb._get_catalog_names()

    # ---- candidate universes: brand aliases, category candidates ----
    brand_entries = [(b["slug"], b["norm"]) for b in catalog["brands"]]
    category_entries = [(slug, norm) for slug, _name, norm in catalog["category_candidates"]]
    brand_norms = [n for _s, n in brand_entries]
    category_norms = [n for _s, n in category_entries]
    log(f"Universe: {len(brand_entries)} brand alias norms, {len(category_entries)} category candidate norms.")

    # ---- source pool A/B: single real corpus words (EN + AR), support>=3 ----
    single_words = [
        (tok, is_arabic(tok)) for tok, pids in idx.postings.items()
        if len(pids) >= MIN_WORD_SUPPORT and tok.isalpha()
    ]
    log(f"Single-word source pool: {len(single_words)} words (support>={MIN_WORD_SUPPORT}).")

    # ---- source pool C: real multi-word product phrases (bigrams/
    # trigrams actually occurring, in order, within real product names,
    # not just co-occurring anywhere) ----
    rng_phrase = random.Random(SEED)
    doc_ids = list(idx.doc_term_freq.keys())
    rng_phrase.shuffle(doc_ids)
    phrase_support: dict[tuple[str, ...], set[int]] = {}
    # re-tokenize per-document text is not stored raw here; use
    # doc_term_freq keys as an approximation is insufficient for ORDER,
    # so instead re-derive phrases from the DB product names directly.
    import psycopg  # noqa: E402
    from src.models.config import settings  # noqa: E402

    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT id, name_en, name_ar FROM product")
        rows = cur.fetchall()

    for pid, name_en, name_ar in rows:
        for name in (name_en, name_ar):
            if not name:
                continue
            toks = tokenize(name, idx.base_freq)
            for n in (2, 3):
                for i in range(len(toks) - n + 1):
                    gram = tuple(toks[i:i + n])
                    if any(len(t) < 2 for t in gram):
                        continue
                    phrase_support.setdefault(gram, set()).add(pid)

    phrase_pool = [
        (gram, len(pids)) for gram, pids in phrase_support.items()
        if len(pids) >= MIN_WORD_SUPPORT
    ]
    log(f"Multi-word phrase pool (real, in-order bigrams/trigrams): {len(phrase_pool)} phrases (support>={MIN_WORD_SUPPORT}).")
    rng_phrase.shuffle(phrase_pool)
    phrase_pool = phrase_pool[:MAX_PHRASE_SOURCES]
    log(f"  capped to {len(phrase_pool)} for tractability.")

    # ---- for each source, best brand match + best category match ----
    entries = []
    entry_id = 0

    def add_entry(source_text: str, source_words: list[str], support: int):
        nonlocal entry_id
        source_norm = kb._normalize_for_fuzzy(source_text)
        lang = "ar" if is_arabic(source_text) else "en"
        window_ids = kb._corpus_cooccurrence_ids(source_words)

        for cand_type, norms, entries_list, product_ids_map in (
            ("brand", brand_norms, brand_entries, catalog["product_ids_by_brand_slug"]),
            ("category", category_norms, category_entries, catalog["product_ids_by_category_slug"]),
        ):
            match = process.extractOne(source_norm, norms, scorer=fuzz.ratio, score_cutoff=SCORE_FLOOR)
            if match is None:
                continue
            matched_norm, score, match_idx = match
            cand_slug = entries_list[match_idx][0]
            cand_ids = product_ids_map.get(cand_slug, set())
            overlap = kb._corpus_overlap_ratio(window_ids, cand_ids) if window_ids else 0.0
            entry_id += 1
            entries.append({
                "id": entry_id,
                "source_text": source_text,
                "language": lang,
                "word_count": len(source_words),
                "char_len": len(source_norm.replace(" ", "")),
                "candidate_type": cand_type,
                "candidate_slug": cand_slug,
                "candidate_norm": matched_norm,
                "fuzzy_score": round(float(score), 2),
                "exact_match": bool(score >= 99.99),
                "corpus_support": len(window_ids),
                "candidate_overlap_ratio": round(overlap, 4),
                "candidate_product_count": len(cand_ids),
            })

    for tok, _arabic in single_words:
        add_entry(tok, [tok], 0)
    log(f"After single-word entries: {len(entries)} collision pairs.")

    for gram, support in phrase_pool:
        text = " ".join(gram)
        add_entry(text, list(gram), support)
    log(f"After phrase entries: {len(entries)} collision pairs total.")

    # ---- summary counts ----
    en_count = sum(1 for e in entries if e["language"] == "en")
    ar_count = sum(1 for e in entries if e["language"] == "ar")
    brand_count = sum(1 for e in entries if e["candidate_type"] == "brand")
    cat_count = sum(1 for e in entries if e["candidate_type"] == "category")
    single_count = sum(1 for e in entries if e["word_count"] == 1)
    multi_count = sum(1 for e in entries if e["word_count"] > 1)
    log(f"Totals: EN={en_count} AR={ar_count} brand={brand_count} category={cat_count} "
        f"single-word={single_count} multi-word={multi_count}")

    # ---- dev/holdout split, seeded, frozen ----
    rng = random.Random(SEED)
    shuffled = entries[:]
    rng.shuffle(shuffled)
    split_idx = int(len(shuffled) * 0.7)
    dev = shuffled[:split_idx]
    holdout = shuffled[split_idx:]
    log(f"Dev/holdout split: dev={len(dev)} holdout={len(holdout)} (seed={SEED})")

    dataset = {
        "seed": SEED,
        "score_floor": SCORE_FLOOR,
        "min_word_support": MIN_WORD_SUPPORT,
        "totals": {
            "total_pairs": len(entries), "en": en_count, "ar": ar_count,
            "brand": brand_count, "category": cat_count,
            "single_word": single_count, "multi_word": multi_count,
        },
        "dev": dev,
        "holdout": holdout,
    }
    out_path = ROOT / "evaluation" / "sprint6_generalization_dataset.json"
    out_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"Full dataset written to {out_path}")

    holdout_path = ROOT / "evaluation" / "sprint6_generalization_holdout.json"
    holdout_doc = {"seed": SEED, "size": len(holdout), "entries": holdout}
    holdout_path.write_text(json.dumps(holdout_doc, ensure_ascii=False, indent=1), encoding="utf-8")
    sha256 = hashlib.sha256(holdout_path.read_bytes()).hexdigest()
    (ROOT / "evaluation" / "sprint6_generalization_holdout.sha256.txt").write_text(sha256 + "\n", encoding="utf-8")
    log(f"Holdout written to {holdout_path} ({len(holdout)} entries)")
    log(f"Holdout SHA-256: {sha256}")


if __name__ == "__main__":
    main()

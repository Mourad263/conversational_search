"""Sprint 6 Part 1: builds the FROZEN blind holdout manifest -- evaluation
artifact only, never imported by or wired into production code. Run once,
before any benchmark scoring, so the vocabulary selection cannot be
influenced by seeing results (spec section 2/3).

Usage: python evaluation/sprint6_build_manifest.py
Writes: evaluation/sprint6_holdout_manifest.json
"""

from __future__ import annotations

import ast
import hashlib
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ingestion.text_normalize import is_arabic, normalize_arabic, normalize_latin  # noqa: E402
from src.search_engine import keyword_baseline as kb  # noqa: E402
from src.search_engine.index import get_index  # noqa: E402

SEED = 20260914
TARGET_EN_WORDS = 40
TARGET_AR_WORDS = 40
TARGET_BRANDS = 25
TARGET_CATEGORIES = 25
MIN_PRODUCT_SUPPORT = 3
MIN_WORD_LEN_EN = 5
MIN_WORD_LEN_AR = 4

_EN_STOPWORDS = {
    "and", "the", "with", "for", "of", "in", "on", "at", "a", "an", "to",
    "or", "no", "not", "per", "free", "pack", "pcs", "piece", "pieces",
    "gm", "gr", "kg", "ml", "l", "size", "new", "extra", "original",
    "value", "pack", "set", "box", "each", "all",
}
_AR_STOPWORDS = {
    normalize_arabic(w) for w in [
        "من", "في", "على", "إلى", "الى", "أو", "او", "مع", "بدون", "غير",
        "هل", "لا", "لأ", "انا", "انتي", "فيه", "فين", "كام", "جرام",
        "كيلو", "لتر", "قطعة", "عبوة", "حجم", "جديد",
    ]
}


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


# ============================================================
# 1. Leakage exclusion vocabulary
# ============================================================

_QUERY_TEXT_CALL_RE = re.compile(
    r"(?:parse_keyword_query|search_keyword|handle_message|understand|run|run_turn|trace|single)\s*\("
    r"[^)]*?(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')",
    re.DOTALL,
)
_CONST_ASSIGN_RE = re.compile(
    r"^[A-Z][A-Z0-9_]*\s*=\s*(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')", re.MULTILINE
)
_JSON_FIELD_RE = re.compile(
    r'["\'](?:q|message)["\']\s*:\s*(\"(?:[^\"\\]|\\.)*\"|\'(?:[^\'\\]|\\.)*\')'
)
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _norm_word(w: str) -> str:
    return normalize_arabic(w) if is_arabic(w) else normalize_latin(w)


def _extract_query_literals(text: str) -> set[str]:
    literals: set[str] = set()
    for pattern in (_QUERY_TEXT_CALL_RE, _CONST_ASSIGN_RE, _JSON_FIELD_RE):
        for m in pattern.finditer(text):
            raw = m.group(1)
            try:
                s = ast.literal_eval(raw)
            except Exception:
                continue
            if isinstance(s, str):
                literals.add(s)
    return literals


def gather_excluded_tokens() -> tuple[set[str], dict]:
    """Returns (excluded_normalized_words, metadata) -- metadata records
    exactly how many literals/words were pulled from each source, for the
    final report's leakage-exclusion accounting."""
    excluded: set[str] = set()
    meta = {"test_query_literals": 0, "test_files_scanned": 0}

    test_files = sorted((ROOT / "tests").rglob("*.py"))
    meta["test_files_scanned"] = len(test_files)
    all_literals: set[str] = set()
    for f in test_files:
        text = f.read_text(encoding="utf-8")
        all_literals |= _extract_query_literals(text)
    meta["test_query_literals"] = len(all_literals)

    for lit in all_literals:
        for w in _WORD_RE.findall(lit):
            excluded.add(_norm_word(w))

    # Production blocklists/aliases (Sprint 5 Part 2/3)
    for w in kb._BRAND_FUZZY_BLOCKLIST:
        excluded.add(kb._normalize_for_fuzzy(w))
    for w in kb._CATEGORY_FUZZY_BLOCKLIST:
        excluded.add(kb._normalize_for_fuzzy(w))
    for aliases in kb._CATEGORY_SINGULAR_ALIASES.values():
        for a in aliases:
            for w in a.split():
                excluded.add(kb._normalize_for_fuzzy(w))
    for aliases in kb._CATEGORY_COMPOUND_ALIASES.values():
        for a in aliases:
            for w in a.split():
                excluded.add(kb._normalize_for_fuzzy(w))
    excluded.add(kb._normalize_for_fuzzy("fat"))
    excluded.add(kb._normalize_for_fuzzy("بدون"))

    # Explicitly-named known-regression examples from the Sprint 5/6 task
    # prompts themselves (this conversation), even if a literal-extraction
    # pass above missed one due to how it's embedded in a test file.
    named_known_examples = [
        "لانشن", "لانشون", "milq", "milk", "choclate", "chocolate",
        "شمبو", "شامنو", "shmapoo", "shampoo", "cookie", "dish", "wafers",
        "lactose", "free", "cream", "cheese", "sugar", "gluten", "oat",
        "oats", "vegan", "fat", "juhayna", "milka", "chocodate", "bonbons",
        "squeasy", "freee", "ahmed", "tea", "coffee", "break", "dove",
        "nivea", "bordonn", "hero", "one", "corona", "fine", "fast",
        "detergent", "detergents",
    ]
    for w in named_known_examples:
        excluded.add(_norm_word(w))

    return excluded, meta


# ============================================================
# 2. Real catalog vocabulary (product words / brands / categories)
# ============================================================

def gather_product_word_candidates(excluded: set[str]) -> dict[str, list[str]]:
    idx = get_index()
    en_words, ar_words = [], []
    for token, pids in idx.postings.items():
        if len(pids) < MIN_PRODUCT_SUPPORT:
            continue
        if token.isdigit() or not token.isalpha():
            continue
        arabic = is_arabic(token)
        if arabic:
            if len(token) < MIN_WORD_LEN_AR or token in _AR_STOPWORDS:
                continue
        else:
            if len(token) < MIN_WORD_LEN_EN or token in _EN_STOPWORDS:
                continue
        if token in excluded:
            continue
        (ar_words if arabic else en_words).append(token)
    return {"en": sorted(set(en_words)), "ar": sorted(set(ar_words))}


def gather_brand_candidates(excluded: set[str]) -> list[dict]:
    catalog = kb._get_catalog_names()
    by_slug: dict[str, list[dict]] = {}
    for b in catalog["brands"]:
        by_slug.setdefault(b["slug"], []).append(b)
    out = []
    for slug, aliases in by_slug.items():
        if kb._normalize_for_fuzzy(slug) in excluded:
            continue
        if any(a["norm"] in excluded for a in aliases):
            continue
        # prefer a Latin-script alias as the canonical "clean" form when
        # available (typo generation is scoped to single-script mutation)
        latin = [a for a in aliases if not is_arabic(a["raw"])]
        pick = latin[0] if latin else aliases[0]
        if len(pick["raw"].strip()) < 4:
            continue
        out.append({"slug": slug, "raw": pick["raw"], "norm": pick["norm"]})
    return out


def gather_category_candidates(excluded: set[str]) -> list[dict]:
    catalog = kb._get_catalog_names()
    by_slug: dict[str, list[tuple[str, str]]] = {}
    for slug, name, norm in catalog["category_candidates"]:
        by_slug.setdefault(slug, []).append((name, norm))
    out = []
    for slug, names in by_slug.items():
        if kb._normalize_for_fuzzy(slug) in excluded:
            continue
        # only offer names that are themselves clean of excluded words
        clean_names = [
            (n, norm) for n, norm in names
            if not any(_norm_word(w) in excluded for w in _WORD_RE.findall(n))
        ]
        if not clean_names:
            continue
        for n, norm in clean_names:
            if len(n.strip()) < 4:
                continue
            out.append({"slug": slug, "name": n.strip(), "norm": norm})
    # de-dupe by slug, keep first clean name found
    seen_slugs = set()
    deduped = []
    for c in out:
        if c["slug"] in seen_slugs:
            continue
        seen_slugs.add(c["slug"])
        deduped.append(c)
    return deduped


# ============================================================
# 3. Deterministic typo mutation
# ============================================================

_EN_ALPHABET = "abcdefghijklmnopqrstuvwxyz"
_AR_ALPHABET = list("ابتثجحخدذرزسشصضطظعغفقكلمنهوي")


def _alphabet_for(word: str) -> list[str]:
    return _AR_ALPHABET if is_arabic(word) else list(_EN_ALPHABET)


def _mutate_deletion(word: str, rng: random.Random) -> str:
    i = rng.randrange(len(word))
    return word[:i] + word[i + 1:]


def _mutate_insertion(word: str, rng: random.Random) -> str:
    i = rng.randrange(len(word) + 1)
    ch = rng.choice(_alphabet_for(word))
    return word[:i] + ch + word[i:]


def _mutate_substitution(word: str, rng: random.Random) -> str:
    i = rng.randrange(len(word))
    alphabet = [c for c in _alphabet_for(word) if c != word[i]]
    ch = rng.choice(alphabet)
    return word[:i] + ch + word[i + 1:]


def _mutate_transposition(word: str, rng: random.Random) -> str | None:
    if len(word) < 2:
        return None
    i = rng.randrange(len(word) - 1)
    if word[i] == word[i + 1]:
        return None
    return word[:i] + word[i + 1] + word[i] + word[i + 2:]


_MUTATORS = {
    "deletion": _mutate_deletion,
    "insertion": _mutate_insertion,
    "substitution": _mutate_substitution,
    "transposition": _mutate_transposition,
}


def generate_typo(word: str, mutation_type: str, rng: random.Random,
                   real_vocab: set[str], max_attempts: int = 25) -> str | None:
    """Deterministic (seeded) mutation, rejecting any result that
    collides with a real vocabulary word/brand/category (spec section 4:
    'reject that mutation and generate another one')."""
    fn = _MUTATORS[mutation_type]
    for _ in range(max_attempts):
        mutated = fn(word, rng)
        if mutated is None:
            continue
        if mutated == word:
            continue
        if _norm_word(mutated) in real_vocab:
            continue
        return mutated
    return None


# ============================================================
# 4. Natural-query templates (typo words embedded in realistic phrasing)
# ============================================================

_EN_TEMPLATES = [
    "I need {word}",
    "show me {word} under 100",
    "do you have {word}",
    "looking for {word}",
]
_AR_TEMPLATES = [
    "عايز {word}",
    "عايز {word} تحت ١٠٠",
    "عندكم {word}؟",
    "وريني {word}",
]


# ============================================================
# Main
# ============================================================

def main() -> None:
    rng = random.Random(SEED)

    log("Gathering leakage-exclusion vocabulary...")
    excluded, excl_meta = gather_excluded_tokens()
    log(f"  {excl_meta['test_files_scanned']} test files scanned, "
        f"{excl_meta['test_query_literals']} query-text literals extracted, "
        f"{len(excluded)} excluded normalized words total (incl. blocklists/aliases).")

    log("Gathering real catalog vocabulary...")
    product_words = gather_product_word_candidates(excluded)
    brands = gather_brand_candidates(excluded)
    categories = gather_category_candidates(excluded)
    log(f"  product word candidates: en={len(product_words['en'])} ar={len(product_words['ar'])}")
    log(f"  brand candidates: {len(brands)}")
    log(f"  category candidates: {len(categories)}")

    # full real-vocabulary set (for mutation-collision rejection) --
    # deliberately NOT the same as `excluded`: a mutation must not
    # accidentally become ANY real word, not just an excluded one.
    idx = get_index()
    real_vocab = set(idx.postings.keys())
    for b in kb._get_catalog_names()["brands"]:
        real_vocab.add(b["norm"])
    for _slug, _name, norm in kb._get_catalog_names()["category_candidates"]:
        real_vocab.add(norm)

    n_en = min(TARGET_EN_WORDS, len(product_words["en"]))
    n_ar = min(TARGET_AR_WORDS, len(product_words["ar"]))
    sampled_en = rng.sample(product_words["en"], n_en)
    sampled_ar = rng.sample(product_words["ar"], n_ar)
    log(f"Sampled {n_en} EN / {n_ar} AR product words (target {TARGET_EN_WORDS}/{TARGET_AR_WORDS}).")

    n_brands = min(TARGET_BRANDS, len(brands))
    sampled_brands = rng.sample(brands, n_brands)
    log(f"Sampled {n_brands} brands (target {TARGET_BRANDS}).")

    n_cats = min(TARGET_CATEGORIES, len(categories))
    sampled_categories = rng.sample(categories, n_cats)
    log(f"Sampled {n_cats} categories (target {TARGET_CATEGORIES}).")

    manifest_entries = []
    entry_id = 0

    def add_word_entries(words: list[str], lang: str, entity_type: str):
        nonlocal entry_id
        for source in words:
            for mtype in ("deletion", "insertion", "substitution", "transposition"):
                mutated = generate_typo(source, mtype, rng, real_vocab)
                if mutated is None:
                    continue
                entry_id += 1
                manifest_entries.append({
                    "id": entry_id,
                    "entity_type": entity_type,
                    "language": lang,
                    "source_clean": source,
                    "mutation_type": mtype,
                    "mutated": mutated,
                    "product_support": len(idx.postings.get(source, ())),
                })

    add_word_entries(sampled_en, "en", "product_word")
    add_word_entries(sampled_ar, "ar", "product_word")

    for b in sampled_brands:
        for mtype in ("deletion", "insertion", "substitution", "transposition"):
            mutated = generate_typo(b["raw"], mtype, rng, real_vocab)
            if mutated is None:
                continue
            entry_id += 1
            manifest_entries.append({
                "id": entry_id,
                "entity_type": "brand",
                "language": "ar" if is_arabic(b["raw"]) else "en",
                "source_clean": b["raw"],
                "canonical_slug": b["slug"],
                "mutation_type": mtype,
                "mutated": mutated,
            })

    for c in sampled_categories:
        for mtype in ("deletion", "insertion", "substitution", "transposition"):
            mutated = generate_typo(c["name"], mtype, rng, real_vocab)
            if mutated is None:
                continue
            entry_id += 1
            manifest_entries.append({
                "id": entry_id,
                "entity_type": "category",
                "language": "ar" if is_arabic(c["name"]) else "en",
                "source_clean": c["name"],
                "canonical_slug": c["slug"],
                "mutation_type": mtype,
                "mutated": mutated,
            })

    # --- Natural-query holdout: random subset of the product-word typo
    # entries embedded into realistic phrase templates (spec section 9)
    word_entries = [e for e in manifest_entries if e["entity_type"] == "product_word"]
    en_word_entries = [e for e in word_entries if e["language"] == "en"]
    ar_word_entries = [e for e in word_entries if e["language"] == "ar"]
    n_natural_en = min(20, len(en_word_entries))
    n_natural_ar = min(20, len(ar_word_entries))
    natural_en_picks = rng.sample(en_word_entries, n_natural_en)
    natural_ar_picks = rng.sample(ar_word_entries, n_natural_ar)

    unseen_brand_names = [b["raw"] for b in sampled_brands]
    natural_queries = []
    nid = 0
    for pick in natural_en_picks:
        nid += 1
        template = _EN_TEMPLATES[nid % len(_EN_TEMPLATES)]
        query = template.format(word=pick["mutated"])
        natural_queries.append({
            "id": nid, "language": "en", "source_entry_id": pick["id"],
            "source_clean": pick["source_clean"], "mutated_word": pick["mutated"],
            "query": query,
        })
    for pick in natural_ar_picks:
        nid += 1
        template = _AR_TEMPLATES[nid % len(_AR_TEMPLATES)]
        query = template.format(word=pick["mutated"])
        natural_queries.append({
            "id": nid, "language": "ar", "source_entry_id": pick["id"],
            "source_clean": pick["source_clean"], "mutated_word": pick["mutated"],
            "query": query,
        })

    # --- Semantic operator (free-from) coverage: every real free-from
    # category in the catalog (small, labeled honestly -- spec section 12)
    free_from_categories = []
    for slug, name, norm in kb._get_catalog_names()["category_candidates"]:
        if any(w in kb._FREE_FROM_MARKERS_NORM for w in norm.split()):
            free_from_categories.append({"slug": slug, "name": name})

    manifest = {
        "seed": SEED,
        "generated_by": "evaluation/sprint6_build_manifest.py",
        "leakage_exclusion": {
            "test_files_scanned": excl_meta["test_files_scanned"],
            "query_text_literals_extracted": excl_meta["test_query_literals"],
            "total_excluded_normalized_words": len(excluded),
            "method": (
                "Scanned every tests/**/*.py file for string literals passed as query "
                "text (calls to parse_keyword_query/search_keyword/handle_message/"
                "understand/run_turn/trace/single, ALL_CAPS constant assignments, and "
                "JSON 'q'/'message' fields), tokenized each into words, and excluded "
                "those normalized words from holdout eligibility. Also excluded every "
                "word in _BRAND_FUZZY_BLOCKLIST, _CATEGORY_FUZZY_BLOCKLIST, "
                "_CATEGORY_SINGULAR_ALIASES, _CATEGORY_COMPOUND_ALIASES, plus a small "
                "explicit list of examples named in the Sprint 5/6 task prompts "
                "themselves. Deliberately scoped to actual query-input text, not every "
                "string literal (e.g. category slugs used only in assertions), per the "
                "task's own instruction not to exclude a whole catalog entry just "
                "because some unrelated test mentions it."
            ),
        },
        "candidate_pool_sizes": {
            "product_words_en": len(product_words["en"]),
            "product_words_ar": len(product_words["ar"]),
            "brands": len(brands),
            "categories": len(categories),
        },
        "sample_sizes": {
            "product_words_en": n_en, "product_words_ar": n_ar,
            "brands": n_brands, "categories": n_cats,
            "natural_queries_en": n_natural_en, "natural_queries_ar": n_natural_ar,
        },
        "vocabulary_entries": manifest_entries,
        "natural_query_holdout": natural_queries,
        "free_from_category_coverage": free_from_categories,
    }

    out_path = ROOT / "evaluation" / "sprint6_holdout_manifest.json"
    out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    sha256 = hashlib.sha256(out_path.read_bytes()).hexdigest()
    log(f"Manifest written to {out_path} ({len(manifest_entries)} vocabulary entries, "
        f"{len(natural_queries)} natural queries).")
    log(f"SHA-256: {sha256}")

    (ROOT / "evaluation" / "sprint6_holdout_manifest.sha256.txt").write_text(
        sha256 + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()

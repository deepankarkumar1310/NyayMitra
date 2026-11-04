"""Pure metric functions used by the evaluation runner (unit-tested, no I/O)."""

import re
import unicodedata


def normalise(text: str) -> str:
    """Lower-case, strip punctuation (keeping letters/marks/digits of any script)."""
    text = unicodedata.normalize("NFC", text.lower())
    kept = [
        ch if unicodedata.category(ch)[0] in {"L", "M", "N"} or ch.isspace() else " "
        for ch in text
    ]
    return re.sub(r"\s+", " ", "".join(kept)).strip()


def edit_distance(ref: list, hyp: list) -> int:
    """Levenshtein distance between two token sequences."""
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1]


def wer(reference: str, hypothesis: str) -> float:
    """Word error rate = word-level edit distance / reference word count."""
    ref, hyp = normalise(reference).split(), normalise(hypothesis).split()
    if not ref:
        return 0.0 if not hyp else 1.0
    return edit_distance(ref, hyp) / len(ref)


def cer(reference: str, hypothesis: str) -> float:
    """Character error rate (more informative than WER for Indic scripts)."""
    ref = list(normalise(reference).replace(" ", ""))
    hyp = list(normalise(hypothesis).replace(" ", ""))
    if not ref:
        return 0.0 if not hyp else 1.0
    return edit_distance(ref, hyp) / len(ref)


def hit_at_k(expected: str, retrieved: list[str], k: int) -> bool:
    return expected in retrieved[:k]


def reciprocal_rank(expected: str, retrieved: list[str]) -> float:
    for rank, doc in enumerate(retrieved, 1):
        if doc == expected:
            return 1.0 / rank
    return 0.0


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    index = min(len(values) - 1, max(0, round(pct / 100 * (len(values) - 1))))
    return values[index]


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None

"""Evaluate NyayMitra end to end and write a Markdown + JSON report.

Run from the backend folder (after `python -m app.ingest`):

    python -m eval.run --retrieval-only      # no API keys needed
    python -m eval.run                       # + Gemini guidance (needs GEMINI_API_KEY)
    python -m eval.run --asr                 # + Whisper WER/CER (needs GROQ_API_KEY and eval/audio/manifest.json)

Metrics
    Retrieval : hit@1, hit@5, MRR - is the right knowledge file retrieved?
    Guidance  : crisis-type accuracy, answers citing >=1 valid source, expected source cited,
                correct "not found" on off-topic questions, response time p50 / p95
    Speech    : WER and CER of Whisper transcripts against reference text, transcription time
"""

import argparse
import json
import mimetypes
import time
from datetime import datetime
from pathlib import Path

from app import config
from app.rag import parse_knowledge_file, retrieve

from .metrics import cer, hit_at_k, mean, percentile, reciprocal_rank, wer

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f} ms"


def doc_urls() -> dict[str, str]:
    return {p.stem: parse_knowledge_file(p)[0]["url"] for p in config.KNOWLEDGE_DIR.glob("*.md")}


def eval_retrieval(dataset: list[dict]) -> tuple[dict, list[dict]]:
    rows = []
    for case in dataset:
        if not case.get("doc"):
            continue
        started = time.perf_counter()
        chunks = retrieve(case["question"], k=config.TOP_K)
        elapsed = (time.perf_counter() - started) * 1000
        docs = [c["doc"] for c in chunks]
        rows.append(
            {
                "id": case["id"],
                "language": case["language"],
                "expected": case["doc"],
                "retrieved": docs,
                "hit1": hit_at_k(case["doc"], docs, 1),
                "hit5": hit_at_k(case["doc"], docs, 5),
                "rr": reciprocal_rank(case["doc"], docs),
                "ms": elapsed,
            }
        )
    summary = {
        "cases": len(rows),
        "hit@1": mean([r["hit1"] for r in rows]),
        "hit@5": mean([r["hit5"] for r in rows]),
        "mrr": mean([r["rr"] for r in rows]),
        "latency_p50_ms": percentile([r["ms"] for r in rows], 50),
    }
    by_lang: dict[str, list] = {}
    for r in rows:
        by_lang.setdefault(r["language"], []).append(r["hit5"])
    summary["hit@5_by_language"] = {k: mean(v) for k, v in sorted(by_lang.items())}
    return summary, rows


def eval_guidance(dataset: list[dict], delay: float) -> tuple[dict, list[dict]]:
    from app.llm import GuidanceError, generate_guidance

    urls = doc_urls()
    trusted = {u.rstrip("/") for u in config.TRUSTED_SOURCES.values()}
    rows = []
    for i, case in enumerate(dataset):
        if i and delay:
            time.sleep(delay)  # stay under free-tier rate limits
        started = time.perf_counter()
        try:
            chunks = retrieve(case["question"], k=config.TOP_K)
            answer = generate_guidance(case["question"], case["language"], chunks)
            error = None
        except GuidanceError as exc:
            answer, error = None, str(exc)
        elapsed = (time.perf_counter() - started) * 1000

        row = {"id": case["id"], "language": case["language"], "ms": elapsed, "error": error}
        if answer:
            cited = {s["url"].rstrip("/") for s in answer["sources"]}
            expected_url = urls.get(case.get("doc") or "", "").rstrip("/")
            row.update(
                {
                    "crisis_expected": case["crisis_type"],
                    "crisis_got": answer["crisis_type"],
                    "crisis_ok": answer["crisis_type"] == case["crisis_type"],
                    "has_valid_source": bool(cited) and cited <= trusted | {u.rstrip("/") for u in urls.values()},
                    "expected_source_cited": (expected_url in cited) if expected_url else None,
                    "not_found": answer["not_found"],
                    "not_found_ok": answer["not_found"] if case.get("expect_not_found") else None,
                    "steps": len(answer["steps"]),
                }
            )
        rows.append(row)

    ok = [r for r in rows if not r["error"]]
    summary = {
        "cases": len(rows),
        "errors": len(rows) - len(ok),
        "crisis_type_accuracy": mean([r["crisis_ok"] for r in ok]),
        "answers_with_valid_source": mean([r["has_valid_source"] for r in ok]),
        "expected_source_cited": mean([r["expected_source_cited"] for r in ok if r["expected_source_cited"] is not None]),
        "off_topic_flagged_not_found": mean([r["not_found_ok"] for r in ok if r["not_found_ok"] is not None]),
        "avg_steps": mean([r["steps"] for r in ok]),
        "latency_p50_ms": percentile([r["ms"] for r in ok], 50),
        "latency_p95_ms": percentile([r["ms"] for r in ok], 95),
    }
    return summary, rows


def eval_asr(manifest_path: Path) -> tuple[dict, list[dict]]:
    from app.stt import TranscriptionError, transcribe_audio

    items = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = []
    for item in items:
        path = manifest_path.parent / item["file"]
        mime = mimetypes.guess_type(path.name)[0] or "audio/wav"
        started = time.perf_counter()
        try:
            hyp = transcribe_audio(path.read_bytes(), path.name, mime, item.get("language"))
            error = None
        except (TranscriptionError, OSError) as exc:
            hyp, error = "", str(exc)
        elapsed = (time.perf_counter() - started) * 1000
        rows.append(
            {
                "file": item["file"],
                "language": item.get("language"),
                "reference": item["reference"],
                "hypothesis": hyp,
                "wer": None if error else wer(item["reference"], hyp),
                "cer": None if error else cer(item["reference"], hyp),
                "ms": elapsed,
                "error": error,
            }
        )
    ok = [r for r in rows if not r["error"]]
    summary = {
        "clips": len(rows),
        "errors": len(rows) - len(ok),
        "mean_wer": mean([r["wer"] for r in ok]),
        "mean_cer": mean([r["cer"] for r in ok]),
        "latency_p50_ms": percentile([r["ms"] for r in ok], 50),
    }
    return summary, rows


def render_markdown(report: dict) -> str:
    lines = [f"# NyayMitra evaluation report", "", f"Generated: {report['generated_at']}", ""]
    r = report.get("retrieval")
    if r:
        s = r["summary"]
        lines += [
            "## Retrieval (MiniLM + ChromaDB)",
            "",
            "| Metric | Value |", "|---|---|",
            f"| Test questions | {s['cases']} |",
            f"| Hit@1 | {_pct(s['hit@1'])} |",
            f"| Hit@5 | {_pct(s['hit@5'])} |",
            f"| MRR | {s['mrr']:.3f} |" if s["mrr"] is not None else "| MRR | n/a |",
            f"| Median retrieval time | {_ms(s['latency_p50_ms'])} |",
            "",
            "Hit@5 by language: " + ", ".join(f"{k}: {_pct(v)}" for k, v in s["hit@5_by_language"].items()),
            "",
        ]
        misses = [row for row in r["rows"] if not row["hit5"]]
        if misses:
            lines += ["Misses (expected file not in top 5):", ""]
            lines += [f"- `{m['id']}` expected `{m['expected']}`, got {m['retrieved'][:3]}" for m in misses]
            lines.append("")
    g = report.get("guidance")
    if g:
        s = g["summary"]
        lines += [
            "## Guidance (Gemini, grounded)",
            "",
            "| Metric | Value |", "|---|---|",
            f"| Test questions | {s['cases']} (errors: {s['errors']}) |",
            f"| Crisis-type accuracy | {_pct(s['crisis_type_accuracy'])} |",
            f"| Answers citing a valid official source | {_pct(s['answers_with_valid_source'])} |",
            f"| Expected source cited | {_pct(s['expected_source_cited'])} |",
            f"| Off-topic questions correctly marked \"not found\" | {_pct(s['off_topic_flagged_not_found'])} |",
            f"| Average steps per answer | {s['avg_steps']:.1f} |" if s["avg_steps"] else "| Average steps per answer | n/a |",
            f"| Response time p50 / p95 | {_ms(s['latency_p50_ms'])} / {_ms(s['latency_p95_ms'])} |",
            "",
        ]
    a = report.get("asr")
    if a:
        s = a["summary"]
        lines += [
            "## Speech-to-text (Groq Whisper)",
            "",
            "| Metric | Value |", "|---|---|",
            f"| Audio clips | {s['clips']} (errors: {s['errors']}) |",
            f"| Mean WER | {_pct(s['mean_wer'])} |",
            f"| Mean CER | {_pct(s['mean_cer'])} |",
            f"| Median transcription time | {_ms(s['latency_p50_ms'])} |",
            "",
        ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=EVAL_DIR / "dataset.json")
    parser.add_argument("--retrieval-only", action="store_true", help="skip the Gemini guidance step")
    parser.add_argument("--asr", action="store_true", help="also evaluate speech-to-text")
    parser.add_argument("--manifest", type=Path, default=EVAL_DIR / "audio" / "manifest.json")
    parser.add_argument("--limit", type=int, default=0, help="only use the first N questions")
    parser.add_argument("--delay", type=float, default=4.0, help="seconds between Gemini calls")
    args = parser.parse_args()

    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    if args.limit:
        dataset = dataset[: args.limit]

    report: dict = {"generated_at": datetime.now().isoformat(timespec="seconds")}

    print(f"Retrieval: {len(dataset)} questions...")
    summary, rows = eval_retrieval(dataset)
    report["retrieval"] = {"summary": summary, "rows": rows}

    if not args.retrieval_only:
        print("Guidance: calling Gemini for each question (this takes a few minutes)...")
        summary, rows = eval_guidance(dataset, args.delay)
        report["guidance"] = {"summary": summary, "rows": rows}

    if args.asr:
        if not args.manifest.exists():
            raise SystemExit(f"{args.manifest} not found - see eval/audio/manifest.example.json")
        print("Speech-to-text: transcribing clips...")
        summary, rows = eval_asr(args.manifest)
        report["asr"] = {"summary": summary, "rows": rows}

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (RESULTS_DIR / f"report-{stamp}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    markdown = render_markdown(report)
    (RESULTS_DIR / f"report-{stamp}.md").write_text(markdown, encoding="utf-8")
    print("\n" + markdown)
    print(f"Saved to {RESULTS_DIR}/report-{stamp}.md")


if __name__ == "__main__":
    main()

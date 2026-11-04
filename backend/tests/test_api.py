"""API and pipeline tests.

Gemini, Groq and ChromaDB are mocked, so these run offline without API keys
or model downloads:
    python -m unittest discover -s tests -v
"""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app import config, main
from app.llm import fallback_answer, parse_json, sanitize_answer
from app.rag import chunk_text, parse_knowledge_file
from app.stt import TranscriptionError

CHUNKS = [
    {
        "text": "File a complaint on SAMADHAN for unpaid wages.",
        "title": "Unpaid wages",
        "source": "SAMADHAN",
        "url": "https://samadhan.labour.gov.in/",
        "score": 0.8,
    }
]

GOOD_ANSWER = {
    "summary": "You have not been paid for three months.",
    "crisis_type": "unpaid_wages",
    "urgency": "high",
    "steps": ["Collect wage proof", "File on SAMADHAN"],
    "document_findings": [],
    "sources": [{"name": "SAMADHAN", "url": "https://samadhan.labour.gov.in/"}],
    "not_found": False,
}


def blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


class SanitizeTests(unittest.TestCase):
    def test_drops_untrusted_urls_and_clamps_enums(self):
        raw = {
            **GOOD_ANSWER,
            "crisis_type": "made_up",
            "urgency": "extreme",
            "sources": [
                {"name": "Fake", "url": "https://fake-portal.example/"},
                {"name": "e-Shram", "url": "https://eshram.gov.in"},
                {"name": "dup", "url": "https://eshram.gov.in/"},
            ],
        }
        out = sanitize_answer(raw, "en", CHUNKS)
        self.assertEqual(out["crisis_type"], "other")
        self.assertEqual(out["urgency"], "medium")
        self.assertEqual([s["name"] for s in out["sources"]], ["e-Shram"])

    def test_empty_steps_returns_fallback(self):
        out = sanitize_answer({"summary": "x", "steps": []}, "hi", [])
        self.assertTrue(out["not_found"])
        self.assertIn("14434", out["steps"][0])

    def test_parse_json_handles_fences(self):
        self.assertEqual(parse_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(parse_json('Here: {"a": 2} done'), {"a": 2})
        with self.assertRaises(ValueError):
            parse_json("[1, 2]")

    def test_fallback_has_trusted_sources(self):
        urls = {s["url"] for s in fallback_answer("en")["sources"]}
        self.assertTrue(urls <= set(config.TRUSTED_SOURCES.values()))


class KnowledgeTests(unittest.TestCase):
    def test_every_knowledge_file_has_trusted_url(self):
        files = list(config.KNOWLEDGE_DIR.glob("*.md"))
        self.assertGreater(len(files), 0)
        trusted = set(config.TRUSTED_SOURCES.values())
        for path in files:
            meta, body = parse_knowledge_file(path)
            self.assertIn(meta["url"], trusted, path.name)
            self.assertTrue(chunk_text(body), path.name)

    def test_chunking_respects_size(self):
        text = "\n\n".join(["word " * 50] * 10)
        self.assertTrue(all(len(c) <= 900 for c in chunk_text(text)))


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [
            patch.object(config, "DB_PATH", Path(self.tmp.name) / "test.db"),
            patch.object(config, "DATA_DIR", Path(self.tmp.name)),
            patch.object(config, "CHROMA_DIR", Path(self.tmp.name) / "chroma"),
            patch("app.main.retrieve", return_value=CHUNKS),
        ]
        for p in self.patches:
            p.start()
        self.guidance = patch("app.main.generate_guidance", return_value=GOOD_ANSWER).start()
        self.patches.append(self.guidance)
        self.client = TestClient(main.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        patch.stopall()
        self.tmp.cleanup()

    def test_health(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["app"], "nyaymitra")

    def test_ask_text_saves_case(self):
        r = self.client.post("/api/ask", data={"text": "3 months no salary", "language": "en"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["crisis_type"], "unpaid_wages")

        cases = self.client.get("/api/cases").json()
        self.assertEqual(len(cases), 1)
        detail = self.client.get(f"/api/cases/{body['id']}").json()
        self.assertEqual(detail["answer"]["steps"], GOOD_ANSWER["steps"])

    def test_ask_requires_input(self):
        r = self.client.post("/api/ask", data={"text": "  ", "language": "hi"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.get("/api/cases").json(), [])

    def test_ask_with_pdf_only(self):
        r = self.client.post(
            "/api/ask",
            data={"language": "hi"},
            files={"file": ("slip.pdf", blank_pdf(), "application/pdf")},
        )
        self.assertEqual(r.status_code, 200, r.text)
        document = self.guidance.call_args.args[3]
        self.assertEqual(document.mime_type, "application/pdf")

    def test_ask_with_image_passes_bytes(self):
        r = self.client.post(
            "/api/ask",
            data={"text": "check this", "language": "en"},
            files={"file": ("slip.png", b"\x89PNG fake", "image/png")},
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(self.guidance.call_args.args[3].is_image)

    def test_rejects_unsupported_file(self):
        r = self.client.post(
            "/api/ask",
            data={"text": "hi"},
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
        self.assertEqual(r.status_code, 400)

    def test_retrieval_failure_still_answers(self):
        with patch("app.main.retrieve", side_effect=RuntimeError("no index")):
            r = self.client.post("/api/ask", data={"text": "injury", "language": "en"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.guidance.call_args.args[2], [])

    def test_unknown_case_404(self):
        self.assertEqual(self.client.get("/api/cases/999").status_code, 404)

    def test_transcribe(self):
        with patch("app.main.transcribe_audio", return_value="वेतन नहीं मिला"):
            r = self.client.post(
                "/api/transcribe",
                files={"audio": ("a.webm", b"audio", "audio/webm")},
                data={"language": "hi"},
            )
        self.assertEqual(r.json(), {"text": "वेतन नहीं मिला"})

    def test_transcribe_missing_key(self):
        with patch.object(config, "GROQ_API_KEY", ""):
            r = self.client.post(
                "/api/transcribe", files={"audio": ("a.webm", b"audio", "audio/webm")}
            )
        self.assertEqual(r.status_code, 502)
        self.assertIn("GROQ_API_KEY", r.json()["detail"])

    def test_transcribe_rejects_non_audio(self):
        r = self.client.post("/api/transcribe", files={"audio": ("a.txt", b"x", "text/plain")})
        self.assertEqual(r.status_code, 415)


if __name__ == "__main__":
    unittest.main()

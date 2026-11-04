"""Tests for multilingual support, admin dashboard API, DB migration and eval metrics."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import config, db, main
from app.llm import FALLBACK_STEPS, FALLBACK_SUMMARY, fallback_answer, sanitize_answer
from app.prompts import build_system_prompt
from app.rag import parse_knowledge_file
from eval.metrics import cer, edit_distance, hit_at_k, normalise, percentile, reciprocal_rank, wer

ANSWER = {
    "summary": "s",
    "crisis_type": "injury",
    "urgency": "critical",
    "steps": ["Call 112"],
    "document_findings": [],
    "sources": [],
    "not_found": False,
}


class LanguageTests(unittest.TestCase):
    def test_every_language_has_fallback_text(self):
        for code in config.LANGUAGES:
            self.assertIn(code, FALLBACK_STEPS)
            self.assertIn(code, FALLBACK_SUMMARY)
            self.assertTrue(fallback_answer(code)["steps"])

    def test_prompt_names_the_language(self):
        self.assertIn("Tamil", build_system_prompt("ta"))
        self.assertIn("Bengali", build_system_prompt("bn"))

    def test_unknown_language_falls_back_to_english(self):
        self.assertEqual(fallback_answer("xx")["summary"], FALLBACK_SUMMARY["en"])
        self.assertEqual(sanitize_answer({"steps": ["a"]}, "xx", [])["summary"], FALLBACK_SUMMARY["en"])


class KnowledgeBaseTests(unittest.TestCase):
    def test_knowledge_base_size_and_unique_titles(self):
        files = sorted(config.KNOWLEDGE_DIR.glob("*.md"))
        self.assertGreaterEqual(len(files), 30)
        titles = [parse_knowledge_file(p)[0]["title"] for p in files]
        self.assertEqual(len(titles), len(set(titles)))

    def test_eval_dataset_points_at_real_files(self):
        dataset = json.loads((Path(__file__).parents[1] / "eval" / "dataset.json").read_text("utf-8"))
        stems = {p.stem for p in config.KNOWLEDGE_DIR.glob("*.md")}
        for case in dataset:
            self.assertIn(case["language"], config.LANGUAGES, case["id"])
            self.assertIn(case["crisis_type"], config.CRISIS_TYPES, case["id"])
            if case.get("doc"):
                self.assertIn(case["doc"], stems, case["id"])


class MetricTests(unittest.TestCase):
    def test_wer(self):
        self.assertEqual(wer("तीन महीने से वेतन नहीं मिला", "तीन महीने से वेतन नहीं मिला"), 0)
        self.assertAlmostEqual(wer("a b c d", "a x c"), 0.5)
        self.assertEqual(wer("Hello, world!", "hello world"), 0)

    def test_cer_and_edit_distance(self):
        self.assertEqual(edit_distance(list("kitten"), list("sitting")), 3)
        self.assertAlmostEqual(cer("abcd", "abed"), 0.25)

    def test_normalise_keeps_indic_marks(self):
        self.assertEqual(normalise("वेतन, नहीं!"), "वेतन नहीं")

    def test_retrieval_metrics(self):
        self.assertTrue(hit_at_k("b", ["a", "b"], 5))
        self.assertFalse(hit_at_k("b", ["a", "b"], 1))
        self.assertEqual(reciprocal_rank("b", ["a", "b"]), 0.5)
        self.assertEqual(reciprocal_rank("z", ["a"]), 0.0)
        self.assertEqual(percentile([1, 2, 3, 4, 5], 50), 3)
        self.assertIsNone(percentile([], 50))


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patch.object(config, "DB_PATH", Path(self.tmp.name) / "t.db").start()
        patch.object(config, "DATA_DIR", Path(self.tmp.name)).start()
        patch.object(config, "CHROMA_DIR", Path(self.tmp.name) / "chroma").start()
        patch("app.main.retrieve", return_value=[]).start()
        patch("app.main.generate_guidance", return_value=ANSWER).start()
        self.client = TestClient(main.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        patch.stopall()
        self.tmp.cleanup()

    def test_stats_counts_cases(self):
        for lang in ["hi", "ta", "ta"]:
            self.client.post("/api/ask", data={"text": "hurt", "language": lang})
        stats = self.client.get("/api/admin/stats").json()
        self.assertEqual(stats["total_cases"], 3)
        self.assertEqual(stats["by_language"][0], {"key": "ta", "count": 2})
        self.assertEqual(stats["by_urgency"], [{"key": "critical", "count": 3}])
        self.assertEqual(len(stats["per_day"]), 14)
        self.assertEqual(stats["per_day"][-1]["count"], 3)
        self.assertIsNotNone(stats["latency_ms"]["p50"])

    def test_tamil_request_is_kept(self):
        r = self.client.post("/api/ask", data={"text": "x", "language": "ta"})
        self.assertEqual(r.json()["language"], "ta")
        r = self.client.post("/api/ask", data={"text": "x", "language": "zz"})
        self.assertEqual(r.json()["language"], config.DEFAULT_LANGUAGE)

    def test_admin_token_required_when_configured(self):
        with patch.object(config, "ADMIN_TOKEN", "secret"):
            self.assertEqual(self.client.get("/api/admin/stats").status_code, 401)
            ok = self.client.get("/api/admin/stats", headers={"X-Admin-Token": "secret"})
            self.assertEqual(ok.status_code, 200)

    def test_delete_case(self):
        case_id = self.client.post("/api/ask", data={"text": "x"}).json()["id"]
        self.assertEqual(self.client.delete(f"/api/admin/cases/{case_id}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/admin/cases/{case_id}").status_code, 404)

    def test_meta_lists_languages(self):
        codes = [l["code"] for l in self.client.get("/api/meta").json()["languages"]]
        self.assertEqual(set(codes), set(config.LANGUAGES))


class MigrationTests(unittest.TestCase):
    def test_old_database_is_upgraded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.db"
            conn = sqlite3.connect(path)
            conn.execute(
                "CREATE TABLE cases (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, "
                "language TEXT NOT NULL, question TEXT NOT NULL, file_name TEXT, answer_json TEXT NOT NULL)"
            )
            conn.execute(
                "INSERT INTO cases (created_at, language, question, answer_json) VALUES (?, ?, ?, ?)",
                ("2026-11-01T10:00:00+00:00", "hi", "q", json.dumps(ANSWER)),
            )
            conn.commit()
            conn.close()
            with patch.object(config, "DB_PATH", path):
                db.init_db()
                case = db.list_cases()[0]
                self.assertEqual(case["crisis_type"], "injury")
                self.assertEqual(db.stats()["total_cases"], 1)


if __name__ == "__main__":
    unittest.main()

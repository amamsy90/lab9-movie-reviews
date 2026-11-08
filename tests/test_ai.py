"""Checks for the trained sentiment artifact and the ai HTTP contract."""
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
import csv
import json
import threading
import unittest
from unittest.mock import patch

from common import Handler
from project import CATEGORIES
from services.ai.app import AI
from services.ai.model import ARTIFACT, TRAINING, Classifier
from services.ai.train import EVAL, evaluate
from tools.smoke import request


@contextmanager
def server(handler):
    http = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{http.server_port}"
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=2)


def rows(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


class SentimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.log_patch = patch.object(Handler, "log_message", lambda *args: None)
        cls.log_patch.start()
        cls.model = Classifier()
        cls.eval_rows = rows(EVAL)
        cls.training_text = {row["text"] for row in rows(TRAINING)}

    @classmethod
    def tearDownClass(cls):
        cls.log_patch.stop()

    def test_artifact_version_is_what_the_service_loads(self):
        saved = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        self.assertEqual(self.model.version, saved["version"])
        self.assertTrue(saved["version"].startswith("nb-v2-"))
        self.assertEqual(set(saved["documents"]), set(CATEGORIES))

    def test_labels_come_from_review_text_not_a_movie_title(self):
        header = TRAINING.read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(header, "text,category")
        self.assertNotIn("movie_title", header)
        title = "Moon Garden"
        positive = self.model.predict(f"{title} was wonderful delightful and excellent")
        negative = self.model.predict(f"{title} was awful boring and dreadful")
        self.assertEqual(positive["category"], "positive")
        self.assertEqual(negative["category"], "negative")
        self.assertEqual(positive["model_version"], self.model.version)

    def test_held_out_examples_are_excluded_and_cover_every_label(self):
        self.assertGreaterEqual(len(self.eval_rows), 3)
        kinds = {row["kind"] for row in self.eval_rows}
        self.assertIn("negation", kinds)
        self.assertIn("mixed", kinds)
        clear = [row for row in self.eval_rows if row["kind"] == "clear"]
        self.assertEqual({row["category"] for row in clear}, set(CATEGORIES))
        for row in self.eval_rows:
            self.assertNotIn(row["text"], self.training_text)

    def test_clear_held_out_rows_match_expected_labels(self):
        for item in evaluate(self.model):
            if item["kind"] != "clear":
                continue
            with self.subTest(text=item["text"]):
                self.assertEqual(item["actual"], item["expected"])

    def test_negation_and_mixed_examples_show_the_word_count_limit(self):
        missed = [item for item in evaluate(self.model) if item["kind"] in ("negation", "mixed")]
        self.assertEqual(len(missed), 2)
        for item in missed:
            self.assertEqual(item["expected"], "negative")
            self.assertEqual(item["actual"], "positive")

    def test_predict_accepts_review_text_and_rejects_empty_or_too_long(self):
        with server(AI) as url:
            status, body = request(url + "/healthz")
            self.assertEqual(status, 200)
            self.assertEqual(body["model_version"], self.model.version)
            status, body = request(url + "/predict", {
                "text": "Wonderful acting and brilliant visuals made a delightful film",
            })
            self.assertEqual(status, 200)
            self.assertEqual(body["category"], "positive")
            self.assertEqual(body["model_version"], self.model.version)
            self.assertEqual(request(url + "/predict", {"text": "x" * 1000})[0], 200)
            for payload in ({"text": ""}, {"text": "   "}, {"text": "x" * 1001}):
                self.assertEqual(request(url + "/predict", payload)[0], 400)


if __name__ == "__main__":
    unittest.main()

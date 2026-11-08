"""Unit and HTTP contract checks; PostgreSQL is exercised by Compose CI."""
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from common import APIError, Handler, MAX_BODY_BYTES, request_json, validate_text
from project import CATEGORIES, PROJECT
from services.ai.app import AI
from services.ai.model import Classifier
from services.web import app as web
from tools.smoke import request, smoke


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


class TestData(Handler):
    """Explicit in-memory test double, never used by the deployed system."""
    tickets = []

    def route(self, method, path):
        if path != "/tickets":
            raise APIError(404, "Not found")
        if method == "GET":
            return self.send(200, self.tickets)
        payload = self.body()
        ticket = {**payload, "id": len(self.tickets) + 1, "created_at": "2026-01-01T00:00:00+00:00"}
        self.tickets.append(ticket)
        return self.send(201, ticket)


class Unavailable(Handler):
    def route(self, method, path):
        raise APIError(503, "Service stopped for test")


class HelperExample(Handler):
    """Tiny routes exercising shared helpers without implementing a project."""
    def route(self, method, path):
        if path == "/upload":
            return self.send(200, {"bytes": len(self.read_body())})
        if path == "/json":
            return self.send(200, self.body())
        if path == "/query":
            return self.send(200, {"q": self.query_param("q"), "category": self.query_param("category")})
        if path == "/method":
            return self.send(200, {"method": method})
        if path == "/html-error":
            return self.send(404, b"<html>Internal proxy details</html>", "text/html")
        if path == "/invalid-response":
            return self.send(200, b"not JSON", "text/plain")
        if path == "/empty":
            return self.send(204, b"", "text/plain")
        errors = {"/missing": (404, "Unknown record ID."), "/duplicate": (409, "Already exists."),
                  "/invalid": (400, "Invalid category."), "/broken": (500, "SECRET=private details")}
        if path in errors:
            raise APIError(*errors[path])
        raise APIError(404, "Not found.")


class ModelTests(unittest.TestCase):
    def test_clear_held_out_inputs_use_all_three_classes(self):
        model = Classifier()
        for example in PROJECT["examples"]:
            text, expected = example["text"], example["category"]
            with self.subTest(text=text):
                self.assertEqual(model.predict(text)["category"], expected)

    def test_training_change_changes_version(self):
        baseline = Classifier()
        source = Path(__file__).resolve().parents[1] / "services/ai/training.csv"
        with tempfile.TemporaryDirectory() as folder:
            dataset = Path(folder) / "training.csv"
            dataset.write_text(source.read_text() + f"Additional synthetic training example,{CATEGORIES[0]}\n")
            self.assertNotEqual(baseline.version, Classifier(dataset).version)

    def test_invalid_text_is_rejected(self):
        for payload in (None, [], {}, {"text": 5}, {"text": "  "}, {"text": "x" * 1001}):
            with self.subTest(payload=payload), self.assertRaises(APIError):
                validate_text(payload)
        self.assertEqual(validate_text({"text": " hello "}), "hello")


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.log_patch = patch.object(Handler, "log_message", lambda *args: None)
        cls.log_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.log_patch.stop()

    def test_full_http_path_and_saved_record_verifier(self):
        TestData.tickets = []
        with server(TestData) as data_url, server(AI) as ai_url:
            with patch.object(web, "DATA_URL", data_url), patch.object(web, "AI_URL", ai_url):
                with server(web.Web) as url, tempfile.TemporaryDirectory() as folder:
                    saved = Path(folder) / "record.json"
                    self.assertIn("PASS", smoke(url, record_file=saved))
                    self.assertIn("unchanged", smoke(url, verify_file=saved))
                    # SQL/HTML-like text remains plain data across the HTTP path.
                    raw = "<script>alert('wifi');</script> DROP TABLE tickets;"
                    status, ticket = request(url + "/api/tickets", {"text": raw})
                    self.assertEqual(status, 201)
                    self.assertEqual(ticket["text"], raw)
                    TestData.tickets[0]["category"] = "tampered"
                    with self.assertRaisesRegex(ValueError, "unchanged"):
                        smoke(url, verify_file=saved)

    def test_website_uses_assigned_project(self):
        from html import escape
        from urllib.request import urlopen

        with server(web.Web) as url:
            with urlopen(url) as response:
                html = response.read().decode()
        self.assertIn(f"<title>{escape(PROJECT['title'])}</title>", html)
        self.assertIn(escape(PROJECT["input_label"]), html)
        self.assertIn(escape(PROJECT["placeholder"], quote=True), html)
        self.assertNotIn("{{", html)

    def test_ai_outage_preserves_history_and_does_not_store_failure(self):
        TestData.tickets = [{"id": 99, "text": "Existing request"}]
        with server(TestData) as data_url, server(Unavailable) as ai_url:
            with patch.object(web, "DATA_URL", data_url), patch.object(web, "AI_URL", ai_url):
                with server(web.Web) as url:
                    self.assertIn("PASS", smoke(url, expect_ai_down=True))
                    self.assertEqual(len(TestData.tickets), 1)

    def test_data_outage_is_not_reported_as_success(self):
        with server(Unavailable) as data_url, server(AI) as ai_url:
            with patch.object(web, "DATA_URL", data_url), patch.object(web, "AI_URL", ai_url):
                with server(web.Web) as url:
                    for payload in (None, {"text": "Wifi is broken"}):
                        status, body = request(url + "/api/tickets", payload)
                        self.assertEqual(status, 503)
                        self.assertIn("error", body)

    def test_bad_input_is_rejected_before_calling_dependencies(self):
        with server(web.Web) as url, patch.object(web, "request_json") as dependency:
            for payload in ([], {"text": ""}, {"text": "x" * 1001}):
                self.assertEqual(request(url + "/api/tickets", payload)[0], 400)
            dependency.assert_not_called()
            self.assertEqual(request(url + "/missing")[0], 404)

    def test_raw_and_json_uploads_over_8kb_and_the_size_boundary(self):
        from http.client import HTTPConnection
        from urllib.parse import urlsplit
        from urllib.request import Request, urlopen

        with server(HelperExample) as url:
            for size in (8193, MAX_BODY_BYTES):
                req = Request(url + "/upload", data=b"x" * size, headers={"Content-Type": "text/csv"})
                with urlopen(req, timeout=5) as response:
                    body = json.load(response)
                    self.assertEqual(response.status, 200)
                    self.assertEqual(body["bytes"], size)
            # Reject an oversized request from its headers, without buffering it.
            connection = HTTPConnection(urlsplit(url).netloc, timeout=5)
            try:
                connection.putrequest("POST", "/upload")
                connection.putheader("Content-Length", str(MAX_BODY_BYTES + 1))
                connection.endheaders()
                with connection.getresponse() as response:
                    self.assertEqual(response.status, 413)
            finally:
                connection.close()
            payload = {"text": "x" * 9000}
            self.assertEqual(request(url + "/json", payload), (200, payload))
            self.assertEqual(request_json(url + "/upload", raw_body=b"x" * 9000, content_type="text/csv"),
                             {"bytes": 9000})
        # Upload limits and the model's semantic text limit are independent.
        with server(AI) as url:
            self.assertEqual(request(url + "/predict", {"text": "x" * 1001})[0], 400)

    def test_query_strings_are_decoded_without_changing_route_matching(self):
        with server(HelperExample) as url:
            self.assertEqual(request(url + "/query?q=ACME%20%26%20Co&category=markets"),
                             (200, {"q": "ACME & Co", "category": "markets"}))
            self.assertEqual(request(url + "/query?q=")[1]["q"], "")
            self.assertEqual(request(url + "/query?q=a&q=b")[0], 400)
        with server(web.Web) as url, patch.object(web, "request_json", return_value=[]) as dependency:
            self.assertEqual(request(url + "/api/tickets?q=ACME%20%26%20Co&category=markets"), (200, []))
            dependency.assert_called_once_with(web.DATA_URL + "/tickets?q=ACME%20%26%20Co&category=markets")

    def test_upstream_client_errors_keep_status_and_public_message(self):
        with server(HelperExample) as url:
            for path, status, message in (("missing", 404, "Unknown record ID."),
                                          ("duplicate", 409, "Already exists."),
                                          ("invalid", 400, "Invalid category."),
                                          ("html-error", 404, "Not Found")):
                with self.subTest(path=path), self.assertRaises(APIError) as caught:
                    request_json(url + "/" + path)
                self.assertEqual(caught.exception.status, status)
                self.assertEqual(str(caught.exception), message)
            for path, status in (("broken", 503), ("invalid-response", 502)):
                with self.assertRaises(APIError) as caught:
                    request_json(url + "/" + path)
                self.assertEqual(caught.exception.status, status)
                self.assertNotIn("SECRET", str(caught.exception))
            for method in ("PUT", "PATCH", "DELETE"):
                self.assertEqual(request_json(url + "/method", method=method), {"method": method})
            self.assertIsNone(request_json(url + "/empty", method="DELETE"))

    def test_malformed_and_missing_body_are_bad_requests(self):
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen

        with server(HelperExample) as url:
            for body in (b"", b"{", b"\xff"):
                with self.assertRaises(HTTPError) as caught:
                    urlopen(Request(url + "/json", data=body), timeout=5)
                with caught.exception as response:
                    self.assertEqual(response.status, 400)


if __name__ == "__main__":
    unittest.main()

"""Checks for the reviews service, using in-memory stand-ins for ai and data."""
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

from common import APIError, Handler, MAX_BODY_BYTES
from services.reviews import app as reviews

SAMPLE = (
    "review_id,movie_title,review_text\n"
    "review-1,Moon Garden,Wonderful acting and brilliant visuals made a delightful film\n"
    "review-2,Moon Garden,The film follows two characters in a coastal town\n"
    "review-3,Cloud Station,Awful acting and boring dialogue made a dreadful movie\n"
)


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


class FakeAI(Handler):
    """Test stand-in for ai: labels by keyword and counts its calls."""
    calls = 0

    def route(self, method, path):
        if (method, path) != ("POST", "/predict"):
            raise APIError(404, "Not found.")
        FakeAI.calls += 1
        text = self.body()["text"].lower()
        label = "positive" if "wonderful" in text else "negative" if "awful" in text else "neutral"
        return self.send(200, {"category": label, "model_version": "test-v1"})


class FakeData(Handler):
    """Test stand-in for data, following the routes agreed in API_CONTRACT.md."""
    rows = []
    prefix = "/reviews/by-external-id/"

    def route(self, method, path):
        if method == "POST" and path == "/reviews":
            review = self.body()
            if any(row["external_id"] == review["external_id"] for row in FakeData.rows):
                raise APIError(409, "Review ID already exists.")
            row = {**review, "id": len(FakeData.rows) + 1, "created_at": "2026-11-08T00:00:00+00:00"}
            FakeData.rows.append(row)
            return self.send(201, row)
        if method == "GET" and path.startswith(self.prefix):
            wanted = unquote(path.removeprefix(self.prefix))
            for row in FakeData.rows:
                if row["external_id"] == wanted:
                    return self.send(200, row)
            raise APIError(404, "Review not found.")
        if method == "GET" and path == "/reviews":
            if self.query_param("all") != "true":
                raise APIError(400, "Counts must ask for all reviews.")
            wanted = self.query_param("movie_title")
            return self.send(200, [row for row in FakeData.rows if row["movie_title"] == wanted])
        raise APIError(404, "Not found.")


class Down(Handler):
    def route(self, method, path):
        raise APIError(503, "Stopped for test.")


def call(url, raw=None, content_type="text/csv"):
    request = Request(url, data=raw, headers={"Content-Type": content_type})
    try:
        response = urlopen(request, timeout=15)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.load(response)


class RuleTests(unittest.TestCase):
    def test_clean_title(self):
        self.assertEqual(reviews.clean_title("  Moon   Garden \t"), "Moon Garden")
        self.assertEqual(reviews.clean_title("   "), "")

    def test_whole_file_errors(self):
        cases = {
            "not utf-8": b"\xff\xfe\x00bad",
            "empty": b"\n\n",
            "missing column": b"review_id,movie_title\nr1,Moon Garden\n",
            "header only": b"review_id,movie_title,review_text\n",
            "21 rows": ("review_id,movie_title,review_text\n"
                        + "".join(f"r{i},Moon Garden,Fine film\n" for i in range(21))).encode(),
        }
        for name, raw in cases.items():
            with self.subTest(name), self.assertRaises(APIError) as caught:
                reviews.parse_csv(raw)
            self.assertEqual(caught.exception.status, 400)

    def test_twenty_rows_blank_lines_bom_and_column_order(self):
        raw = ("﻿review_text,review_id,movie_title\n\n"
               + "".join(f"Fine film,r{i},Moon Garden\n" for i in range(20))).encode()
        rows = reviews.parse_csv(raw)
        self.assertEqual(len(rows), 20)
        self.assertEqual(rows[0][1], {"review_id": "r0", "movie_title": "Moon Garden", "review_text": "Fine film"})

    def test_quoted_commas_and_html_stay_as_text(self):
        raw = b'review_id,movie_title,review_text\nr1,Moon Garden,"Odd, but <b>fine</b>"\n'
        self.assertEqual(reviews.parse_csv(raw)[0][1]["review_text"], "Odd, but <b>fine</b>")

    def test_lost_race_on_save_counts_as_duplicate(self):
        stored = {"external_id": "r1", "movie_title": "Moon Garden", "review_text": "Fine film"}
        with patch.object(reviews, "find_review", side_effect=[None, stored]), \
                patch.object(reviews, "classify", return_value=("neutral", "test-v1")), \
                patch.object(reviews, "save_review", side_effect=APIError(409, "Taken.")):
            self.assertEqual(reviews.store("r1", "Moon Garden", "Fine film"), "duplicate")


class ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.log_patch = patch.object(Handler, "log_message", lambda *args: None)
        cls.log_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.log_patch.stop()

    def setUp(self):
        FakeData.rows = []
        FakeAI.calls = 0

    @contextmanager
    def running(self, ai=FakeAI, data=FakeData):
        with server(ai) as ai_url, server(data) as data_url, \
                patch.object(reviews, "AI_URL", ai_url), patch.object(reviews, "DATA_URL", data_url), \
                server(reviews.Reviews) as url:
            yield url

    def test_health(self):
        with self.running() as url:
            self.assertEqual(call(url + "/healthz"), (200, {"service": "reviews", "status": "ok"}))
            self.assertEqual(call(url + "/nope")[0], 404)

    def test_import_saves_labels_and_model_version(self):
        with self.running() as url:
            status, result = call(url + "/imports", SAMPLE.encode())
        self.assertEqual(status, 200)
        self.assertEqual((result["added"], result["duplicates"], result["skipped"]), (3, 0, 0))
        self.assertEqual([row["status"] for row in result["rows"]], ["added"] * 3)
        self.assertEqual([(row["external_id"], row["sentiment"], row["model_version"]) for row in FakeData.rows],
                         [("review-1", "positive", "test-v1"), ("review-2", "neutral", "test-v1"),
                          ("review-3", "negative", "test-v1")])

    def test_reimport_adds_nothing_and_skips_the_model(self):
        with self.running() as url:
            call(url + "/imports", SAMPLE.encode())
            before = list(FakeData.rows)
            status, result = call(url + "/imports", SAMPLE.encode())
        self.assertEqual((status, result["added"], result["duplicates"], result["skipped"]), (200, 0, 3, 0))
        self.assertEqual(FakeData.rows, before)
        self.assertEqual(FakeAI.calls, 3)

    def test_reused_id_with_different_review_is_rejected(self):
        changed = SAMPLE.replace("coastal town", "mountain village")
        with self.running() as url:
            call(url + "/imports", SAMPLE.encode())
            _, result = call(url + "/imports", changed.encode())
        self.assertEqual((result["added"], result["duplicates"], result["skipped"]), (0, 2, 1))
        self.assertEqual(result["rows"][1]["reason"], "review_id already used for a different review")
        self.assertIn("coastal town", FakeData.rows[1]["review_text"])

    def test_review_ids_with_slashes_and_spaces_reach_data_intact(self):
        raw = b"review_id,movie_title,review_text\nbatch 1/r#1?x,Moon Garden,Wonderful film\n"
        with self.running() as url:
            first = call(url + "/imports", raw)[1]
            second = call(url + "/imports", raw)[1]
        self.assertEqual((first["added"], second["duplicates"]), (1, 1))
        self.assertEqual(FakeData.rows[0]["external_id"], "batch 1/r#1?x")

    def test_repeats_inside_one_file(self):
        raw = (SAMPLE + "review-1,Moon Garden,Wonderful acting and brilliant visuals made a delightful film\n"
               "review-2,Moon Garden,Something else entirely\n").encode()
        with self.running() as url:
            _, result = call(url + "/imports", raw)
        self.assertEqual((result["added"], result["duplicates"], result["skipped"]), (3, 1, 1))
        self.assertEqual(len(FakeData.rows), 3)

    def test_bad_rows_are_skipped_and_good_rows_still_saved(self):
        raw = ("review_id,movie_title,review_text\n"
               "r1,  Moon   Garden ,Wonderful film\n"
               "r2,,Wonderful film\n"
               ",Moon Garden,Wonderful film\n"
               f"r4,Moon Garden,{'x' * 1001}\n"
               "r5,Moon Garden\n").encode()
        with self.running() as url:
            _, result = call(url + "/imports", raw)
        self.assertEqual((result["added"], result["duplicates"], result["skipped"]), (1, 0, 4))
        self.assertEqual([row["reason"] for row in result["rows"][1:]],
                         ["movie_title is blank", "review_id is blank",
                          "review_text is longer than 1000 characters", "review_text is blank"])
        self.assertEqual(FakeData.rows[0]["movie_title"], "Moon Garden")

    def test_ai_down_skips_rows_without_saving(self):
        with self.running(ai=Down) as url:
            status, result = call(url + "/imports", SAMPLE.encode())
        self.assertEqual((status, result["added"], result["skipped"]), (200, 0, 3))
        self.assertEqual({row["reason"] for row in result["rows"]}, {"service unavailable"})
        self.assertEqual(FakeData.rows, [])

    def test_data_down_skips_rows_and_counts_fail_clearly(self):
        with self.running(data=Down) as url:
            _, result = call(url + "/imports", SAMPLE.encode())
            status, error = call(url + "/counts?movie_title=Moon%20Garden")
        self.assertEqual((result["added"], result["skipped"]), (0, 3))
        self.assertEqual(FakeAI.calls, 0)
        self.assertEqual((status, error), (503, {"error": "A required service is unavailable. Please try again."}))

    def test_upload_limits(self):
        with self.running() as url:
            # Rejected from the size header alone, before reading the body.
            connection = HTTPConnection(urlsplit(url).netloc, timeout=5)
            try:
                connection.putrequest("POST", "/imports")
                connection.putheader("Content-Length", str(MAX_BODY_BYTES + 1))
                connection.endheaders()
                with connection.getresponse() as response:
                    self.assertEqual(response.status, 413)
            finally:
                connection.close()
            status, error = call(url + "/imports", b"review_id,movie_title\nr1,Moon Garden\n")
        self.assertEqual((status, error), (400, {"error": "The CSV header is missing: review_text."}))

    def test_counts(self):
        with self.running() as url:
            call(url + "/imports", SAMPLE.encode())
            self.assertEqual(call(url + "/counts?movie_title=%20Moon%20%20Garden"),
                             (200, {"movie_title": "Moon Garden", "positive": 1, "neutral": 1,
                                    "negative": 0, "total": 2}))
            self.assertEqual(call(url + "/counts?movie_title=Unknown")[1],
                             {"movie_title": "Unknown", "positive": 0, "neutral": 0, "negative": 0, "total": 0})
            self.assertEqual(call(url + "/counts?movie_title=%20%20"), (400, {"error": "Choose a movie."}))
            self.assertEqual(call(url + "/counts")[0], 400)


if __name__ == "__main__":
    unittest.main()

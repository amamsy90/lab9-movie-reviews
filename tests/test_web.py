"""Checks for the movie-review website routes, using stand-ins for reviews and data."""
from contextlib import contextmanager
from http.client import HTTPConnection
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
from urllib.request import urlopen

from common import APIError, Handler, MAX_BODY_BYTES
from services.reviews import app as reviews
from services.web import app as web
from test_reviews import SAMPLE, Down, FakeAI, FakeData, call, server


class FakeDataForWeb(FakeData):
    """Adds the list and movie routes the website reads (API_CONTRACT.md)."""

    def route(self, method, path):
        if method == "GET" and path == "/movies":
            return self.send(200, sorted({row["movie_title"] for row in FakeData.rows}))
        if method == "GET" and path == "/reviews" and self.query_param("all") != "true":
            movie, sentiment = self.query_param("movie_title"), self.query_param("sentiment")
            rows = [row for row in reversed(FakeData.rows)
                    if (not movie or row["movie_title"] == movie)
                    and (not sentiment or row["sentiment"] == sentiment)]
            return self.send(200, rows)
        return super().route(method, path)


class EchoReviews(Handler):
    """Records what the website forwards to reviews."""
    last = None

    def route(self, method, path):
        if (method, path) == ("POST", "/imports"):
            EchoReviews.last = (self.headers.get("Content-Type"), self.read_body())
            return self.send(200, {"added": 0, "duplicates": 0, "skipped": 0, "rows": []})
        if (method, path) == ("GET", "/counts"):
            EchoReviews.last = self.query_param("movie_title")
            return self.send(200, {"movie_title": EchoReviews.last, "positive": 0,
                                   "neutral": 0, "negative": 0, "total": 0})
        raise APIError(400, "The CSV header is missing: review_text.")


class WebTests(unittest.TestCase):
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
        EchoReviews.last = None

    @contextmanager
    def site(self, reviews_handler=None, data=FakeDataForWeb):
        """The website, wired to the real reviews service (or a stand-in) and fake ai/data."""
        with server(FakeAI) as ai_url, server(data) as data_url, \
                patch.object(reviews, "AI_URL", ai_url), patch.object(reviews, "DATA_URL", data_url), \
                server(reviews_handler or reviews.Reviews) as reviews_url, \
                patch.object(web, "REVIEWS_URL", reviews_url), patch.object(web, "DATA_URL", data_url), \
                server(web.Web) as url:
            yield url

    def test_page_has_the_review_board_controls(self):
        with self.site() as url, urlopen(url) as response:
            html = response.read().decode()
        for control in ('id="csv-file"', 'id="movie"', 'id="sentiment"', 'id="counts"', 'id="reviews"'):
            self.assertIn(control, html)
        self.assertNotIn("{{", html)
        self.assertNotIn("innerHTML", html)   # review text is only ever set as plain text

    def test_import_list_filter_and_counts_through_real_reviews(self):
        with self.site() as url:
            status, result = call(url + "/api/imports", SAMPLE.encode())
            self.assertEqual((status, result["added"], result["duplicates"], result["skipped"]), (200, 3, 0, 0))
            self.assertEqual(call(url + "/api/movies"), (200, ["Cloud Station", "Moon Garden"]))
            status, listed = call(url + "/api/reviews")
            self.assertEqual((status, len(listed)), (200, 3))
            _, moon = call(url + "/api/reviews?movie_title=Moon%20Garden")
            self.assertEqual({row["external_id"] for row in moon}, {"review-1", "review-2"})
            _, positive = call(url + "/api/reviews?movie_title=Moon%20Garden&sentiment=positive")
            self.assertEqual([row["external_id"] for row in positive], ["review-1"])
            self.assertEqual(call(url + "/api/counts?movie_title=Moon%20Garden")[1],
                             {"movie_title": "Moon Garden", "positive": 1, "neutral": 1, "negative": 0, "total": 2})
            # Refresh and reimport: nothing new, counts unchanged.
            _, again = call(url + "/api/imports", SAMPLE.encode())
            self.assertEqual((again["added"], again["duplicates"]), (0, 3))
            self.assertEqual(len(call(url + "/api/reviews")[1]), 3)
            self.assertEqual(call(url + "/api/counts?movie_title=Moon%20Garden")[1]["total"], 2)

    def test_csv_is_forwarded_unchanged_and_errors_keep_their_message(self):
        with self.site(reviews_handler=EchoReviews) as url:
            raw = "review_id,movie_title,review_text\nr1,Café Lune,Très bien\n".encode()
            self.assertEqual(call(url + "/api/imports", raw)[0], 200)
            self.assertEqual(EchoReviews.last, ("text/csv", raw))
            self.assertEqual(call(url + "/api/counts?movie_title=%20Moon%20%20Garden")[0], 200)
            self.assertEqual(EchoReviews.last, "Moon Garden")
            self.assertEqual(call(url + "/api/nothing"), (404, {"error": "Not found."}))

    def test_bad_requests_are_rejected_before_calling_services(self):
        with self.site() as url, patch.object(web, "request_json") as dependency:
            self.assertEqual(call(url + "/api/counts"), (400, {"error": "Choose a movie."}))
            self.assertEqual(call(url + "/api/counts?movie_title=" + "x" * 201)[0], 400)
            self.assertEqual(call(url + "/api/reviews?sentiment=happy"),
                             (400, {"error": "Choose positive, neutral or negative."}))
            self.assertEqual(call(url + "/api/imports", b"")[0], 400)
            connection = HTTPConnection(urlsplit(url).netloc, timeout=5)
            try:
                connection.putrequest("POST", "/api/imports")
                connection.putheader("Content-Length", str(MAX_BODY_BYTES + 1))
                connection.endheaders()
                with connection.getresponse() as response:
                    self.assertEqual(response.status, 413)
            finally:
                connection.close()
            dependency.assert_not_called()

    def test_import_file_errors_from_reviews_reach_the_page(self):
        with self.site() as url:
            status, error = call(url + "/api/imports", b"review_id,movie_title\nr1,Moon Garden\n")
        self.assertEqual((status, error), (400, {"error": "The CSV header is missing: review_text."}))

    def test_services_down_show_a_clear_error(self):
        with self.site(reviews_handler=Down, data=Down) as url:
            expected = (503, {"error": "A required service is unavailable. Please try again."})
            self.assertEqual(call(url + "/api/imports", SAMPLE.encode()), expected)
            self.assertEqual(call(url + "/api/counts?movie_title=Moon%20Garden"), expected)
            self.assertEqual(call(url + "/api/reviews"), expected)
            self.assertEqual(call(url + "/api/movies"), expected)


if __name__ == "__main__":
    unittest.main()

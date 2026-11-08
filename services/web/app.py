"""Public website and request orchestrator. Never connects to PostgreSQL."""
import os
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from common import APIError, Handler, request_json, serve, validate_text
from project import CATEGORIES, PROJECT

DATA_URL = os.environ.get("DATA_URL", "http://data:8000")
AI_URL = os.environ.get("AI_URL", "http://ai:8000")
REVIEWS_URL = os.environ.get("REVIEWS_URL", "http://reviews:8000")
IMPORT_TIMEOUT = 60      # up to 20 rows, each may call ai and data
MAX_TITLE = 200

page = Path(__file__).with_name("index.html").read_text(encoding="utf-8")
for key in ("title", "goal", "input_guidance", "input_label", "placeholder", "history_title"):
    page = page.replace("{{" + key + "}}", escape(PROJECT[key], quote=True))
HTML = page.encode("utf-8")


def movie_param(handler, required=False):
    title = " ".join(handler.query_param("movie_title").split())
    if required and not title:
        raise APIError(400, "Choose a movie.")
    if len(title) > MAX_TITLE:
        raise APIError(400, f"Movie title must be at most {MAX_TITLE} characters.")
    return title


class Web(Handler):
    def route(self, method, path):
        if method == "GET" and path == "/":
            return self.send(200, HTML, "text/html; charset=utf-8")
        if method == "GET" and path == "/healthz":
            return self.send(200, {"service": "web", "status": "ok"})

        # Movie-review board.
        if method == "POST" and path == "/api/imports":
            csv_file = self.read_body()
            result = request_json(f"{REVIEWS_URL}/imports", raw_body=csv_file,
                                  content_type="text/csv", timeout=IMPORT_TIMEOUT)
            return self.send(200, result)
        if method == "GET" and path == "/api/counts":
            query = urlencode({"movie_title": movie_param(self, required=True)})
            return self.send(200, request_json(f"{REVIEWS_URL}/counts?{query}"))
        if method == "GET" and path == "/api/reviews":
            filters = {"movie_title": movie_param(self), "sentiment": self.query_param("sentiment")}
            if filters["sentiment"] and filters["sentiment"] not in CATEGORIES:
                raise APIError(400, "Choose positive, neutral or negative.")
            query = urlencode({key: value for key, value in filters.items() if value})
            return self.send(200, request_json(f"{DATA_URL}/reviews" + (f"?{query}" if query else "")))
        if method == "GET" and path == "/api/movies":
            return self.send(200, request_json(f"{DATA_URL}/movies"))

        # Starter baseline, kept for CI and tools/smoke.py.
        if method == "GET" and (path == "/api/tickets" or path.startswith("/api/tickets/")):
            query = f"?{self.query_string}" if self.query_string else ""
            return self.send(200, request_json(f"{DATA_URL}{path.removeprefix('/api')}{query}"))
        if method == "POST" and path == "/api/tickets":
            text = validate_text(self.body())
            prediction = request_json(f"{AI_URL}/predict", {"text": text})
            ticket = request_json(f"{DATA_URL}/tickets", {"text": text, **prediction})
            return self.send(201, ticket)
        raise APIError(404, "Not found.")


if __name__ == "__main__":
    serve(Web)

"""Public website and request orchestrator. Never connects to PostgreSQL."""
import os
from html import escape
from pathlib import Path

from common import APIError, Handler, request_json, serve, validate_text
from project import PROJECT

DATA_URL = os.environ.get("DATA_URL", "http://data:8000")
AI_URL = os.environ.get("AI_URL", "http://ai:8000")
page = Path(__file__).with_name("index.html").read_text()
for key in ("title", "goal", "input_guidance", "input_label", "placeholder", "history_title"):
    page = page.replace("{{" + key + "}}", escape(PROJECT[key], quote=True))
HTML = page.encode("utf-8")


class Web(Handler):
    def route(self, method, path):
        if method == "GET" and path == "/":
            return self.send(200, HTML, "text/html; charset=utf-8")
        if method == "GET" and path == "/healthz":
            return self.send(200, {"service": "web", "status": "ok"})
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

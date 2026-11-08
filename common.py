"""Small HTTP helpers shared at build time, not a fourth service."""
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

MAX_BODY_BYTES = 1024 * 1024


class APIError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def request_json(url, payload=None, *, method=None, timeout=5,
                 raw_body=None, content_type="application/json"):
    """Call a service, preserving its public 4xx errors, but not server internals."""
    if raw_body is not None and payload is not None:
        raise ValueError("Supply either payload or raw_body, not both.")
    data = raw_body if raw_body is not None else (None if payload is None else json.dumps(payload).encode())
    request = Request(url, data=data, method=method, headers={"Content-Type": content_type})
    try:
        with urlopen(request, timeout=timeout) as response:
            return None if response.status == 204 else json.load(response)
    except HTTPError as error:
        with error:
            if 400 <= error.code < 500:
                try:
                    message = HTTPStatus(error.code).phrase
                except ValueError:
                    message = "Request rejected by a required service."
                try:
                    payload = json.loads(error.read(8192))
                    detail = payload.get("error") if isinstance(payload, dict) else None
                    if isinstance(detail, str) and 0 < len(detail) <= 500:
                        message = detail
                except (OSError, ValueError):
                    pass
                raise APIError(error.code, message) from error
        raise APIError(503, "A required service is unavailable. Please try again.") from error
    except (URLError, TimeoutError, OSError) as error:
        raise APIError(503, "A required service is unavailable. Please try again.") from error
    except ValueError as error:
        raise APIError(502, "A required service returned an invalid response.") from error


def validate_text(payload):
    value = payload.get("text") if isinstance(payload, dict) else None
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 1000:
        raise APIError(400, "Enter between 1 and 1000 characters.")
    return value.strip()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Request paths/status only. Never log request text or credentials.
        print(f"{self.address_string()} {format % args}", flush=True)

    def send(self, status, payload, content_type="application/json"):
        body = json.dumps(payload).encode() if content_type == "application/json" else payload
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def read_body(self, max_bytes=MAX_BODY_BYTES):
        """Read bounded raw bytes, e.g. an XML/CSV file sent as the request body."""
        if self.headers.get("Transfer-Encoding"):
            raise APIError(400, "Send a Content-Length body; chunked uploads are not supported.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise APIError(400, "Invalid content length.") from error
        if length <= 0:
            raise APIError(400, "A nonempty request body is required.")
        if length > max_bytes:
            self.close_connection = True
            raise APIError(413, f"Request body must be at most {max_bytes} bytes.")
        try:
            data = self.rfile.read(length)
        except TimeoutError as error:
            self.close_connection = True
            raise APIError(408, "Request body timed out.") from error
        if len(data) != length:
            raise APIError(400, "Incomplete request body.")
        return data

    def body(self, max_bytes=MAX_BODY_BYTES):
        """Decode a JSON body; raw file uploads should use read_body() instead."""
        data = self.read_body(max_bytes)
        try:
            return json.loads(data)
        except (ValueError, UnicodeError) as error:
            raise APIError(400, "Invalid JSON.") from error

    def query_param(self, name, default=""):
        values = self.query.get(name)
        if values is None:
            return default
        if len(values) != 1:
            raise APIError(400, f"Supply {name} only once.")
        return values[0]

    def dispatch(self):
        try:
            try:
                url = urlsplit(self.path)
                self.query_string = url.query
                self.query = parse_qs(url.query, keep_blank_values=True, max_num_fields=100)
            except ValueError as error:
                raise APIError(400, "Invalid query string.") from error
            self.route(self.command, url.path)
        except APIError as error:
            self.send(error.status, {"error": str(error)})
        except Exception:
            # Do not leak SQL, connection strings, or stack traces to visitors.
            print("Unhandled request error", flush=True)
            self.send(500, {"error": "An internal error occurred."})

    do_GET = dispatch
    do_POST = dispatch
    do_PUT = dispatch
    do_PATCH = dispatch
    do_DELETE = dispatch


def serve(handler):
    class Server(ThreadingHTTPServer):
        daemon_threads = True

        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(15)
            return connection, address

    Server(("0.0.0.0", int(os.environ.get("PORT", "8000"))), handler).serve_forever()

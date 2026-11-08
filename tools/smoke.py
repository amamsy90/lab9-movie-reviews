#!/usr/bin/env python3
"""Check the public request path, retained records, or an intentional AI outage."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

# Read relative to this file so both direct CLI and imported test use work.
PROJECT = json.loads((Path(__file__).resolve().parents[1] / "project.json").read_text())


def request(url, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    req = Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        response = urlopen(req, timeout=15)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.load(response)


def check(condition, message):
    if not condition:
        raise ValueError(message)


def verify_saved(url, expected):
    status, tickets = request(f"{url}/api/tickets")
    check(status == 200 and isinstance(tickets, list), "History must return a JSON list with HTTP 200.")
    check(expected in tickets, f"Original record #{expected.get('id')} was not read back unchanged.")


def smoke(url, record_file=None, verify_file=None, expect_ai_down=False):
    check(urlsplit(url).scheme in ("http", "https") and bool(urlsplit(url).netloc), "Use an http(s) URL.")
    url = url.rstrip("/")
    if verify_file:
        expected = json.loads(Path(verify_file).read_text())
        verify_saved(url, expected)
        return f"PASS: original record #{expected['id']} is unchanged."
    if expect_ai_down:
        status, tickets = request(f"{url}/api/tickets")
        check(status == 200 and isinstance(tickets, list), "History must work during an AI outage.")
        status, result = request(f"{url}/api/tickets", {"text": "Smoke outage test: " + PROJECT["placeholder"]})
        check(status == 503 and bool(result.get("error")), "AI outage must produce a clear HTTP 503 error.")
        return "PASS: history works and new submission reports the AI outage."
    text = f"Smoke test {datetime.now(timezone.utc).isoformat()}: {PROJECT['placeholder']}"
    status, ticket = request(f"{url}/api/tickets", {"text": text})
    check(status == 201, f"Expected creation HTTP 201, received {status}: {ticket}")
    check(isinstance(ticket.get("id"), int), "Missing integer ticket ID.")
    check(ticket.get("text") == text, "Input text was not preserved.")
    check(ticket.get("category") in PROJECT["categories"], "Invalid category for the assigned project.")
    check(bool(ticket.get("model_version")) and bool(ticket.get("created_at")), "Missing model version or timestamp.")
    verify_saved(url, ticket)
    status, result = request(f"{url}/api/tickets", {"text": "   "})
    check(status == 400 and bool(result.get("error")), "Blank input must be rejected with HTTP 400.")
    if record_file:
        Path(record_file).write_text(json.dumps(ticket, indent=2) + "\n")
    return f"PASS: created and read back record #{ticket['id']}; blank input rejected."


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--record-file", type=Path)
    mode.add_argument("--verify-file", type=Path)
    mode.add_argument("--expect-ai-down", action="store_true")
    args = parser.parse_args()
    try:
        print(smoke(args.url, args.record_file, args.verify_file, args.expect_ai_down))
    except (OSError, ValueError, TypeError, AttributeError) as error:
        parser.exit(1, f"FAIL: {error}\n")


if __name__ == "__main__":
    main()

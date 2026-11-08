"""Movie-review processing service: CSV import and per-movie sentiment counts.

Asks `ai` for each new review's sentiment and saves reviews through `data`.
Never connects to PostgreSQL.
"""
import csv
import io
import os
from urllib.parse import quote, urlencode

from common import APIError, Handler, request_json, serve
from project import CATEGORIES

AI_URL = os.environ.get("AI_URL", "http://ai:8000")
DATA_URL = os.environ.get("DATA_URL", "http://data:8000")

MAX_ROWS = 20
COLUMNS = ("review_id", "movie_title", "review_text")
# The same limits as data (and ai's 1000-character text limit), API_CONTRACT.md.
LIMITS = {"review_id": 100, "movie_title": 200, "review_text": 1000}
UNAVAILABLE = "service unavailable"


# --- Connection points --------------------------------------------------------
# Every call to ai and data goes through these four functions. Routes are the
# ones agreed in API_CONTRACT.md.

def classify(text):
    """ai: POST /predict {"text"} -> {"category", "model_version"}."""
    result = request_json(f"{AI_URL}/predict", {"text": text})
    sentiment = result.get("category") if isinstance(result, dict) else None
    version = result.get("model_version") if isinstance(result, dict) else None
    if sentiment not in CATEGORIES or not isinstance(version, str) or not version:
        raise APIError(502, "The classifier returned an invalid response.")
    return sentiment, version


def find_review(review_id):
    """data: GET /reviews/by-external-id/{review_id} -> the review, or None on 404."""
    try:
        review = request_json(f"{DATA_URL}/reviews/by-external-id/{quote(review_id, safe='')}")
    except APIError as error:
        if error.status == 404:
            return None
        raise
    if not isinstance(review, dict):
        raise APIError(502, "The data service returned an invalid response.")
    return review


def save_review(review):
    """data: POST /reviews -> 201 saved review; 409 means the review_id is taken."""
    return request_json(f"{DATA_URL}/reviews", review)


def movie_reviews(movie_title):
    """data: GET /reviews?movie_title=...&all=true -> every review for one movie."""
    rows = request_json(f"{DATA_URL}/reviews?{urlencode({'movie_title': movie_title, 'all': 'true'})}")
    if not isinstance(rows, list):
        raise APIError(502, "The data service returned an invalid response.")
    return rows


# --- Rules --------------------------------------------------------------------

def clean_title(title):
    """Trim the ends and collapse repeated spaces: '  Moon   Garden ' -> 'Moon Garden'."""
    return " ".join(title.split())


def parse_csv(raw):
    """Check the whole file and return [(row_number, {column: value}), ...]."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise APIError(400, "The file must be a UTF-8 CSV.") from error
    try:
        records = [(number, row) for number, row in enumerate(csv.reader(io.StringIO(text, newline="")), 1)]
    except csv.Error as error:
        raise APIError(400, "The file could not be read as a CSV.") from error
    records = [(number, row) for number, row in records if any(cell.strip() for cell in row)]
    if not records:
        raise APIError(400, "The file is empty.")

    header = [name.strip() for name in records[0][1]]
    missing = [column for column in COLUMNS if column not in header]
    if missing:
        raise APIError(400, "The CSV header is missing: " + ", ".join(missing) + ".")
    positions = {column: header.index(column) for column in COLUMNS}

    rows = records[1:]
    if not rows:
        raise APIError(400, "The file has no review rows.")
    if len(rows) > MAX_ROWS:
        raise APIError(400, f"The file has {len(rows)} review rows; the limit is {MAX_ROWS}.")
    return [
        (number, {column: row[index] if index < len(row) else "" for column, index in positions.items()})
        for number, row in rows
    ]


def check_row(row):
    """Return (review_id, movie_title, review_text) cleaned, or raise ValueError with the reason."""
    values = {
        "review_id": row["review_id"].strip(),
        "movie_title": clean_title(row["movie_title"]),
        "review_text": row["review_text"].strip(),
    }
    for column in COLUMNS:
        if not values[column]:
            raise ValueError(f"{column} is blank")
        if len(values[column]) > LIMITS[column]:
            raise ValueError(f"{column} is longer than {LIMITS[column]} characters")
    return values["review_id"], values["movie_title"], values["review_text"]


def same_review(stored, movie_title, review_text):
    return stored.get("movie_title") == movie_title and stored.get("review_text") == review_text


def import_csv(raw):
    rows = parse_csv(raw)
    results = []
    seen = {}            # review_id -> (title, text) already handled in this file
    services_down = False

    for number, row in rows:
        entry = {"row": number, "review_id": row["review_id"].strip()}
        results.append(entry)
        try:
            review_id, movie_title, review_text = check_row(row)
        except ValueError as reason:
            entry.update(status="skipped", reason=str(reason))
            continue

        if review_id in seen:
            if seen[review_id] == (movie_title, review_text):
                entry["status"] = "duplicate"
            else:
                entry.update(status="skipped", reason="review_id used twice in this file for different reviews")
            continue
        if services_down:
            entry.update(status="skipped", reason=UNAVAILABLE)
            continue

        try:
            entry["status"] = store(review_id, movie_title, review_text)
        except APIError as error:
            if error.status >= 500:
                services_down = True
                entry.update(status="skipped", reason=UNAVAILABLE)
            else:
                entry.update(status="skipped", reason=str(error))
            continue
        if entry["status"] == "conflict":
            entry.update(status="skipped", reason="review_id already used for a different review")
            continue
        seen[review_id] = (movie_title, review_text)

    statuses = [entry["status"] for entry in results]
    return {
        "added": statuses.count("added"),
        "duplicates": statuses.count("duplicate"),
        "skipped": statuses.count("skipped"),
        "rows": results,
    }


def store(review_id, movie_title, review_text):
    """Return 'added', 'duplicate' or 'conflict' for one checked row."""
    existing = find_review(review_id)
    if existing is not None:
        return "duplicate" if same_review(existing, movie_title, review_text) else "conflict"
    sentiment, version = classify(review_text)
    try:
        save_review({
            "external_id": review_id,
            "movie_title": movie_title,
            "review_text": review_text,
            "sentiment": sentiment,
            "model_version": version,
        })
    except APIError as error:
        if error.status != 409:
            raise
        # Someone saved this ID between our lookup and our save.
        existing = find_review(review_id)
        if existing is None:
            raise
        return "duplicate" if same_review(existing, movie_title, review_text) else "conflict"
    return "added"


def sentiment_counts(movie_title):
    title = clean_title(movie_title)
    if not title:
        raise APIError(400, "Choose a movie.")
    if len(title) > LIMITS["movie_title"]:
        raise APIError(400, f"movie_title must be at most {LIMITS['movie_title']} characters.")
    counts = dict.fromkeys(CATEGORIES, 0)
    for review in movie_reviews(title):
        sentiment = review.get("sentiment") if isinstance(review, dict) else None
        if sentiment not in counts:
            raise APIError(502, "The data service returned an invalid review.")
        counts[sentiment] += 1
    return {"movie_title": title, **counts, "total": sum(counts.values())}


class Reviews(Handler):
    def route(self, method, path):
        if method == "GET" and path == "/healthz":
            return self.send(200, {"service": "reviews", "status": "ok"})
        if method == "POST" and path == "/imports":
            return self.send(200, import_csv(self.read_body()))
        if method == "GET" and path == "/counts":
            return self.send(200, sentiment_counts(self.query_param("movie_title")))
        raise APIError(404, "Not found.")


if __name__ == "__main__":
    serve(Reviews)

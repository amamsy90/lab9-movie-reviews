# `reviews` microservice: evidence

Owner: @gatekg. Checkpoint I1 (implementation). Code: `services/reviews/app.py`. Tests: `tests/test_reviews.py`.

## API documentation and request/response examples

Errors are always `{"error": "<message>"}`.

**`GET /healthz`** → `200 {"service": "reviews", "status": "ok"}`

**`POST /imports`**: the CSV file is the raw request body (`Content-Type: text/csv`), with columns `review_id`, `movie_title`, `review_text` in any order.

```
review_id,movie_title,review_text
review-1,Moon Garden,Wonderful acting and brilliant visuals made a delightful film
review-2,Moon Garden,The film follows two characters in a coastal town
review-3,Cloud Station,Awful acting and boring dialogue made a dreadful movie
```

```json
200 {"added": 3, "duplicates": 0, "skipped": 0,
     "rows": [{"row": 2, "review_id": "review-1", "status": "added"},
              {"row": 3, "review_id": "review-2", "status": "added"},
              {"row": 4, "review_id": "review-3", "status": "added"}]}
```

Importing the same file again returns `{"added": 0, "duplicates": 3, "skipped": 0, ...}`, and nothing is saved twice.

Row rules:

| Row | Result |
| --- | --- |
| New `review_id`, valid fields | `added`: labelled by `ai`, saved through `data` with sentiment and model version |
| Same `review_id`, title and text as a stored review (or an earlier row in the file) | `duplicate`: nothing saved, `ai` not called |
| `review_id` already used for a different title or text | `skipped`: "review_id already used for a different review" |
| Blank field, or text over 1000 characters | `skipped`, with the reason |
| `ai` or `data` unavailable | `skipped`: "service unavailable" (later rows are skipped without waiting) |

Movie titles are cleaned before saving: ends trimmed and repeated spaces collapsed (`"  Moon   Garden "` → `"Moon Garden"`).

Whole-file errors (nothing imported): `413` over 1 MiB; `400` for non-UTF-8, an empty file, missing columns, no review rows, or more than 20 review rows.

**`GET /counts?movie_title=Moon%20Garden`**: counts from every stored review for that movie, retrieved through `data`.

```json
200 {"movie_title": "Moon Garden", "positive": 1, "neutral": 1, "negative": 0, "total": 2}
```

A movie with no reviews returns zeros. `400` for a blank title. `503` if `data` is unavailable.

## Test commands and results

```
python -m unittest discover -s tests -v
Ran 35 tests ... OK (skipped=8)
```

The 13 `test_reviews` tests cover: a good import with labels and model version saved; reimport adding nothing and not calling the model again; a reused ID with different text rejected and the stored review unchanged; repeats inside one file; blank and over-long fields; title cleanup; quoted commas and HTML kept as plain text; empty, non-UTF-8, missing-column, header-only and 21-row files; the 1 MiB limit; counts including zeros and a blank title; `ai` down and `data` down; and a save race returning 409. The 8 skipped tests are the starter's PostgreSQL tests, which run in CI.

## Build/start commands and configuration names

```
docker compose up -d --build --wait
docker compose ps
```

Environment: `AI_URL` (default `http://ai:8000`), `DATA_URL` (default `http://data:8000`), `PORT` (default `8000`). `web` receives `REVIEWS_URL=http://reviews:8000`.

## Deployed service check (time and result)

Local Docker, 8 Nov 2026: all five containers healthy (`ai`, `data`, `db`, `reviews`, `web`). Public deployment pending.

## Processing and real ML/storage API checks

Local Docker, 8 Nov 2026, from inside the `reviews` container:

- `GET /healthz` → `200 {"service": "reviews", "status": "ok"}`
- Real `ai` call → `positive`, model version `nb-v1-ffcd63596016` (starter model; the trained model is pending)
- Real `data` calls → `404 Not found`: the review routes are not built yet. The import reported the row as skipped with that reason instead of failing.
- `tools/smoke.py` baseline → PASS

Connecting to the real `data` review routes and the full import → counts check is checkpoint I2, after the routes are agreed in PR #1.

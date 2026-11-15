# `reviews` microservice: evidence

Owner: @gatekg. Checkpoints I1 (implementation, #2) and I2 (integration and release). Code: `services/reviews/app.py`. Tests: `tests/test_reviews.py`.

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

Environment: `AI_URL` (default `http://ai:8000`), `DATA_URL` (default `http://data:8000`), `SERVICE_TIMEOUT` (seconds to wait for `ai` or `data`, default `90`), `PORT` (default `8000`). On Render (`render.yaml`, service `lab9-reviews`), `AI_URL` and `DATA_URL` point at the public `lab9-ai` and `lab9-data` URLs. `web` receives `REVIEWS_URL=http://reviews:8000`.

## Deployed service check (time and result)

Local Docker, 8 Nov 2026: all five containers healthy (`ai`, `data`, `db`, `reviews`, `web`).

Public Render service, 15 Nov 2026, 13:00 Asia/Dubai: `GET https://lab9-reviews.onrender.com/healthz` → `200 {"service": "reviews", "status": "ok"}`.

## Processing and real ML/storage API checks

Earlier local Docker run, 8 Nov 2026, from inside the `reviews` container (before the trained model and the `data` review routes were merged):

- `GET /healthz` → `200 {"service": "reviews", "status": "ok"}`
- Real `ai` call → `positive`, model version `nb-v1-ffcd63596016` (starter model; the trained model is pending)
- Real `data` calls → `404 Not found`: the review routes are not built yet. The import reported the row as skipped with that reason instead of failing.
- `tools/smoke.py` baseline → PASS

I2: `reviews` now calls the `data` routes agreed in `API_CONTRACT.md` (`GET /reviews/by-external-id/{review_id}`, `POST /reviews`, `GET /reviews?movie_title=...&all=true`). Tests: 36 OK (8 skipped for PostgreSQL), including review IDs with spaces and slashes. The full import → counts check against the real `data` service runs once its routes are merged.

## I2: integration and release

- **Waking services.** Render's free services sleep after 15 idle minutes and take about a minute to wake. `reviews` now waits up to `SERVICE_TIMEOUT` (90 s) for `ai` and `data` instead of the 5-second default, so the first import after a quiet period labels its rows instead of skipping them as "service unavailable". Tests: `test_slow_ai_is_waited_for_instead_of_skipping_the_row` (an `ai` answering after 5.5 s; it fails on the old code) and `test_every_call_to_ai_and_data_waits_for_a_waking_service`.
- **Real `reviews` → `data` → PostgreSQL.** Maitha's pipeline tests in `tests/test_database.py` (#8) run this service against the real `data` service and PostgreSQL in CI: import, filters, counts over 100 reviews, identical reimport, conflicting IDs, file limits, and `ai`/database failures.
- **Live, 15 Nov 2026, through https://lab9-movie-reviews.onrender.com:**
  - 12:32 Asia/Dubai: a fresh 7-row CSV for *The Tin Kite* and *Glass Harbour* (IDs `gk-1115-01` to `gk-1115-07`, last row with a blank review) saved 6 reviews with model `nb-v2-6aa22689257b`. Counts: *The Tin Kite* 1 positive / 1 neutral / 1 negative, *Glass Harbour* 2 / 0 / 1. The negative filter for *The Tin Kite* returns only `gk-1115-03`.
  - 13:00 Asia/Dubai: reimporting the same file → `0 added, 6 duplicates, 1 skipped` ("review_text is blank"); both movies' counts unchanged.
  - Aishah's separate run (12:51, *Silver Harbor* and *Lantern Fields*) is recorded in `SUBMISSION.md`.
- **Release configuration.** `render.yaml` now has the `lab9-reviews` entry (Dockerfile, `/healthz`, `AI_URL`, `DATA_URL`).

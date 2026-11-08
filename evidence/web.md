# Website microservice: evidence

Owner: @gatekg. Checkpoint W1 (implementation). Code: `services/web/app.py`, `services/web/index.html`. Tests: `tests/test_web.py`.

## API documentation and request/response examples

The browser only calls `web`. Errors are `{"error": "<message>"}`, and errors from `reviews` or `data` are passed through with the same status and message.

| Browser route | Passes to | Example reply |
| --- | --- | --- |
| `POST /api/imports` (CSV file as the raw body, `Content-Type: text/csv`) | `reviews POST /imports` | `200 {"added": 3, "duplicates": 0, "skipped": 0, "rows": [...]}` |
| `GET /api/counts?movie_title=Moon%20Garden` | `reviews GET /counts` | `200 {"movie_title": "Moon Garden", "positive": 1, "neutral": 1, "negative": 0, "total": 2}` |
| `GET /api/reviews?movie_title=Moon%20Garden&sentiment=positive` (both optional) | `data GET /reviews` | `200 [{"external_id": "review-1", "movie_title": "Moon Garden", "sentiment": "positive", ...}]` |
| `GET /api/movies` | `data GET /movies` | `200 ["Cloud Station", "Moon Garden"]` |
| `GET /healthz` | none | `200 {"service": "web", "status": "ok"}` |

Checked by `web` before calling any service: an empty upload (`400`), an upload over 1 MiB (`413`, rejected from the size header), a missing or over-200-character movie title for counts (`400 "Choose a movie."`), and a sentiment filter other than positive, neutral or negative (`400`). Services that are down give `503 "A required service is unavailable. Please try again."`

The starter's `/api/tickets` routes are unchanged (used by CI and `tools/smoke.py`).

## Test commands and results

```
python -m unittest discover -s tests -v
Ran 42 tests ... OK (skipped=8)
```

The 6 `test_web` tests cover: the page controls are present and review text is never inserted as HTML; import → movie list → filtered list → counts → reimport through the real `reviews` service (with stand-ins for `ai` and `data`), where the reimport adds nothing and the counts stay the same; the CSV reaching `reviews` byte for byte; bad requests rejected before any service is called; a file error from `reviews` reaching the page; and `reviews`/`data` being down. The 8 skipped tests are the starter's PostgreSQL tests, which run in CI.

## Build/start commands and configuration names

```
docker compose up -d --build --wait
docker compose ps
```

Environment: `REVIEWS_URL` (default `http://reviews:8000`), `DATA_URL` (default `http://data:8000`), `AI_URL` (default `http://ai:8000`, starter tickets only), `PORT` (default `8000`). Compose publishes the site on `${WEB_BIND:-127.0.0.1}:${WEB_PORT:-8080}`.

## Deployed service check (time and result)

Local Docker, 8 Nov 2026: all five containers healthy; `GET /` serves the review board; `tools/smoke.py --url http://127.0.0.1:8080` → PASS. `/api/counts` returned `404 Not found` because the `data` review routes are not merged yet. Public deployment pending.

## Browser workflow and public HTTPS check

Local browser check, 8 Nov 2026 (real `web` and `reviews`, stand-ins for `ai` and `data`), with a fresh CSV for two fictional movies, *Silver Harbor* and *Lantern Fields*, including one blank review and one review containing `<script>`:

1. Import → "4 added · 0 duplicates · 1 skipped", with "Row 6 (lf-2): review_text is blank". `"  Silver   Harbor "` was saved as "Silver Harbor".
2. Movie filter *Silver Harbor* → "3 reviews in total", counts 1 positive / 1 neutral / 1 negative, three reviews listed. Adding the *negative* filter → 1 review.
3. Reimport of the same file → "0 added · 4 duplicates · 1 skipped"; counts still 1 / 1 / 1.
4. The `<script>` review was shown as plain text and did not run.
5. A 25-row file → "The file has 25 review rows; the limit is 20." shown as an error, and nothing was imported.

Public HTTPS check pending deployment (W2).

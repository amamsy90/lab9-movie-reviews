# Movie review board: API contract

Draft for team-01. Each owner defines their own service: `web` and `reviews` (Ghaith), `ai` (Aishah), `data` + PostgreSQL (Maitha). `web`, `reviews`, and `ai` are defined below. Maitha still fills in `data`.

## Shared rules (from the starter and the brief)

- Each service listens on `0.0.0.0` and `PORT` (default `8000`) and has `GET /healthz`.
- Errors are `{"error": "<plain message>"}` with a 4xx/5xx status, as `common.py` already does.
- Sentiment labels: `positive`, `neutral`, `negative` (from `project.json`).
- The baseline `/api/tickets`, `/tickets` and `/predict` routes stay working (CI and `tools/smoke.py` use them).

## Call map

```
browser ──> web ──> reviews ──> ai
             │         └──────> data
             └────────────────> data
                                data ──> PostgreSQL
```

## `ai` (Aishah)

The starter `POST /predict` contract stays. `reviews` sends one review body and stores the returned `category` and `model_version`. Do not send `movie_title`. The classifier uses the review text only. The movie title is not a sentiment label.

**`POST /predict`**

```json
{"text": "Wonderful acting and brilliant visuals made a delightful film"}
```

```json
response: 200 {"category": "positive", "model_version": "nb-v2-<training-file-hash>"}
```

- `category` is `positive`, `neutral`, or `negative`.
- `text` is required, must not be blank, and must be at most 1000 characters. `reviews` should apply that same limit before calling.
- Bad text returns `400` with `{"error": "Enter between 1 and 1000 characters."}`. That covers missing text, blank text, and text over 1000 characters.
- If `ai` is down, `reviews` keeps its own row status (`skipped`, reason "service unavailable"). `ai` does not invent a label for that case.

**`GET /healthz`** stays as in the starter: `200 {"service": "ai", "status": "ok", "model_version": "<version>"}`.

No other `ai` route. There is no batch endpoint.

A1 plan, so `reviews` can build against this shape now:

- Train a CPU Naive Bayes classifier on labeled review text and save `services/ai/artifact.json`.
- Load that artifact when `ai` starts and return its version on every prediction. The version string can change when the training file changes; store whatever `model_version` comes back.
- Keep empty-text rejection and the 1000-character limit.
- Evaluate held-out reviews for every label, including a negation example and a mixed-sentiment example, and record the word-count limitation in `evidence/ai.md`.

## What `reviews` and `web` need from `data` (Maitha to define)

1. **Save one review**: review_id, movie title, review text, sentiment, model version. What happens if the review_id is already stored?
2. **Look up a stored review by its review_id**, so `reviews` can tell a repeat of the same review from a different review reusing an ID, and avoid calling `ai` for repeats.
3. **List reviews for the website**, filtered by movie and/or sentiment.
4. **Get every stored review for one movie** (no page limit), so `reviews` can build the counts.
5. **List movie titles** for the website's movie filter (optional; `web` can manage without it).
6. Field limits (review_id, title, text lengths), and the route names, query names and reply shape.

## `reviews` (Ghaith)

Movie titles are cleaned before saving and before counting: spaces trimmed at both ends and repeated spaces collapsed to one (`"  Moon   Garden "` → `"Moon Garden"`).

**`POST /imports`**: the CSV file is sent as the raw request body (`Content-Type: text/csv`).

```
review_id,movie_title,review_text
review-1,Moon Garden,Wonderful acting and brilliant visuals made a delightful film
```

```json
response: 200 {"added": 1, "duplicates": 0, "skipped": 0,
               "rows": [{"row": 2, "review_id": "review-1", "status": "added"}]}
```

What happens to each row:

| Situation | Status |
| --- | --- |
| New review_id with valid fields | `added` (labelled by `ai`, saved through `data`) |
| review_id already stored, or seen earlier in this file, with the same title and text | `duplicate` (nothing saved, `ai` not called) |
| review_id already used for a different title or text | `skipped`, reason "review_id already used for a different review" |
| Blank field, or a field over the agreed limit | `skipped`, with a reason |
| `ai` or `data` fails for this row | `skipped`, reason "service unavailable" |

Skipped rows carry a `"reason"`. Rows already added stay saved if a later row fails.

Whole-file errors (nothing imported):

- `413`: file over 1 MiB.
- `400`: not UTF-8, header missing `review_id`, `movie_title` or `review_text`, no data rows, or more than 20 data rows.

**`GET /counts?movie_title=Moon%20Garden`**: counts from all stored reviews for that movie.

```json
response: 200 {"movie_title": "Moon Garden", "positive": 1, "neutral": 1, "negative": 0, "total": 2}
```

- A movie with no reviews returns all zeros. `400` if `movie_title` is missing or blank. `503` if `data` is unreachable.

## `web` (Ghaith): public routes the browser calls

| Browser route | Passes to |
| --- | --- |
| `POST /api/imports` (raw CSV body) | `reviews POST /imports` |
| `GET /api/counts?movie_title=` | `reviews GET /counts` |
| `GET /api/reviews?movie_title=&sentiment=` | `data` review list (route set by Maitha) |
| `GET /api/movies` | `data` movie list, if Maitha provides one |

`web` returns errors from `reviews` and `data` to the browser unchanged (status and message).

## Configuration names

| Service | Variables |
| --- | --- |
| `web` | `DATA_URL`, `AI_URL` (baseline), `REVIEWS_URL` |
| `reviews` | `AI_URL`, `DATA_URL` |
| `ai` | `PORT` only (default `8000`). `reviews` calls `AI_URL`. No database variables. |
| `data` | set by Maitha (starter uses `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`) |

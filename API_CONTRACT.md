# Movie review board: API contract

Agreed by team-01. Each owner defines their own service: `web` and `reviews` (Ghaith), `ai` (Aishah), `data` + PostgreSQL (Maitha).

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

## `data` (Maitha)

Only `data` connects directly to PostgreSQL. The existing `/tickets` API stays for baseline compatibility. `GET /healthz` is provided.

All saved review responses use:

```json
{
  "id": 1,
  "external_id": "review-1",
  "movie_title": "Moon Garden",
  "review_text": "Wonderful acting and brilliant visuals made a delightful film",
  "sentiment": "positive",
  "model_version": "nb-v2-example",
  "created_at": "2026-11-08T12:00:00+00:00"
}
```

**1. Save one review: `POST /reviews`**

```json
{
  "external_id": "review-1",
  "movie_title": "Moon Garden",
  "review_text": "Wonderful acting and brilliant visuals made a delightful film",
  "sentiment": "positive",
  "model_version": "nb-v2-example"
}
```

- New review: HTTP 201, returning the saved review.
- Existing `external_id`: HTTP 409 with `{"error": "Review ID already exists."}`.
- PostgreSQL enforces uniqueness, so duplicates cannot create extra rows.

**2. Look up a review by review_id: `GET /reviews/by-external-id/{review_id}`**

- HTTP 200: returns the stored review.
- HTTP 404: `{"error": "Review not found."}`.

The `reviews` service can compare the stored title and text with the incoming normalized values to identify identical duplicates or conflicting ID reuse before calling AI.

**3. List and filter reviews: `GET /reviews`**

Optional query parameters: `movie_title`, `sentiment`.

- `GET /reviews`
- `GET /reviews?movie_title=Moon%20Garden`
- `GET /reviews?sentiment=positive`
- `GET /reviews?movie_title=Moon%20Garden&sentiment=positive`

Response: HTTP 200, a JSON array of saved review objects.

**4. Get all reviews for one movie: `GET /reviews?movie_title=Moon%20Garden&all=true`**

Returns every matching review without the default 100-row limit. The `reviews` service can use this for accurate sentiment counts. An unknown movie returns `[]`.

**5. List movie titles: `GET /movies`**

```json
["Moon Garden", "Silver Harbor"]
```

The list contains distinct movie titles, sorted alphabetically.

**6. Field limits and validation**

- `external_id`: 1–100 characters, nonblank.
- `movie_title`: 1–200 characters after whitespace normalization.
- `review_text`: 1–1000 characters, nonblank.
- `sentiment`: exactly `positive`, `neutral`, or `negative`.
- `model_version`: 1–100 characters, nonblank.

Invalid input returns HTTP 400 with `{"error": "..."}`.

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
| `GET /api/reviews?movie_title=&sentiment=` | `data GET /reviews` |
| `GET /api/movies` | `data GET /movies` |

`web` returns errors from `reviews` and `data` to the browser unchanged (status and message).

## Configuration names

| Service | Variables |
| --- | --- |
| `web` | `DATA_URL`, `AI_URL` (baseline), `REVIEWS_URL` |
| `reviews` | `AI_URL`, `DATA_URL` |
| `ai` | `PORT` only (default `8000`). `reviews` calls `AI_URL`. No database variables. |
| `data` | `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` (as in the starter) |

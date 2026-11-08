# Movie review board: component assignments

Read [STUDENT_GUIDE.md](STUDENT_GUIDE.md) for shared delivery, review, and deployment requirements. [PROJECT.md](PROJECT.md) defines the product scope and examiner's workflow.

### W1 — Create and deploy the website microservice

**Owner:** W. **Service:** `web`. **Evidence:** [evidence/web.md](evidence/web.md).

- Upload a movie-review CSV and show added, duplicate, and skipped/failed row counts for the current import.
- List reviews with movie titles and predicted sentiment; filter by movie and sentiment.
- Display positive, neutral, and negative review counts for the selected movie.

### I1 — Create and deploy the movie-review processing microservice

**Owner:** I. **Service:** `reviews`. **Evidence:** [evidence/reviews.md](evidence/reviews.md).

- Expose CSV-import and per-movie sentiment-count HTTP endpoints. Require review_id, movie_title, and review_text; normalize movie-title whitespace.
- Call ai for each new review and save it, its sentiment, and model version through data.
- Deduplicate by review_id: identical reimports preserve existing rows; reject conflicting reuse of an ID.
- Calculate positive, neutral, and negative counts using all stored reviews for the selected movie, retrieved through data. Return zeros for an empty result.
- Limit each CSV to 1 MiB and 20 rows. Return added, duplicate, and skipped/failed counts for this request.

### A1 — Create and deploy a sentiment-classification microservice

**Owner:** A. **Service:** `ai`. **Evidence:** [evidence/ai.md](evidence/ai.md).

Train and deploy a CPU classifier for the review text, without using the movie title as a sentiment label with labels `positive`, `neutral`, `negative`, returning the predicted label and trained-model version. Follow the mandatory training and evaluation requirements in [STUDENT_GUIDE.md](STUDENT_GUIDE.md).

- Return positive, neutral, or negative. Include an unseen mixed-sentiment or negation example in the evaluation and explain the limitation.

### D1 — Create and deploy the PostgreSQL database and database-access microservice

**Owner:** D. **Deliverables:** PostgreSQL DATABASE and the `data` service. **Evidence:** [evidence/data.md](evidence/data.md).

Design, migrate, and deploy the database for: reviews (id, unique external_id, movie_title, review_text, sentiment, model_version, created_at).

- Enforce unique external review IDs and valid sentiment labels. Identical reimports must not duplicate rows.
- Provide create/list APIs, movie/sentiment filters, and complete review retrieval for per-movie counts.

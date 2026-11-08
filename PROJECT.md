# Movie review board

Variant: `movie-reviews`. Shared requirements: [STUDENT_GUIDE.md](STUDENT_GUIDE.md). Component assignments: [TASKS.md](TASKS.md).

## Product

Import movie reviews, classify sentiment, and view simple sentiment counts for each movie.

Upload a CSV with review_id, movie_title, and review_text. Browse the classified reviews and view positive, neutral, and negative counts for a selected movie.

## Scope

Use fictional movies and reviews. CSV is the only required input mode. Percentages, charts, saved import history, external movie APIs, review scraping, user accounts, and star-rating prediction are not required.

## Sample input

Use the included [sample-input.csv](https://maai-se-lab9.inemo.chatgpt.site/examples/movie-reviews/sample-input.csv) to get started, then test with fresh synthetic input. Any `example.com` links are placeholders.

## Examiner's workflow

1. Import a fresh CSV of reviews for two fictional movies and see saved reviews with sentiment predictions.
2. Filter by movie and sentiment and verify that movie's sentiment counts.
3. Refresh and reimport the same CSV: review IDs/counts and per-movie counts remain unchanged.

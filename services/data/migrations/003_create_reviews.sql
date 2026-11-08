
-- Create a table to store movie reviews and AI predictions.
CREATE TABLE IF NOT EXISTS reviews (
    -- Unique ID generated automatically by PostgreSQL.
    id BIGSERIAL PRIMARY KEY,

    -- Original review ID from the uploaded CSV.
    external_id TEXT NOT NULL UNIQUE,

    -- Name of the movie being reviewed.
    movie_title TEXT NOT NULL,

    -- Original text written by the reviewer.
    review_text TEXT NOT NULL,

    -- Sentiment predicted by the AI model.
    sentiment TEXT NOT NULL
        CHECK (sentiment IN ('positive', 'neutral', 'negative')),

    -- Version of the AI model used for the prediction.
    model_version TEXT NOT NULL,

    -- Time when the review was saved.
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Prevent empty review IDs, movie names, and review texts.
    CONSTRAINT reviews_external_id_not_blank
        CHECK (LENGTH(TRIM(external_id)) > 0),

    CONSTRAINT reviews_movie_title_not_blank
        CHECK (LENGTH(TRIM(movie_title)) > 0),

    CONSTRAINT reviews_review_text_not_blank
        CHECK (LENGTH(TRIM(review_text)) > 0),

    CONSTRAINT reviews_model_version_not_blank
        CHECK (LENGTH(TRIM(model_version)) > 0)
);

-- Speed up searches for reviews belonging to a movie.
CREATE INDEX IF NOT EXISTS idx_reviews_movie_title
    ON reviews (movie_title);

-- Speed up filtering by movie and sentiment.
CREATE INDEX IF NOT EXISTS idx_reviews_movie_sentiment
    ON reviews (movie_title, sentiment);

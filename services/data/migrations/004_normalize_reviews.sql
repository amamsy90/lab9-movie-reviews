-- Create a separate table for unique movie titles.
CREATE TABLE movies (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL UNIQUE,
    CONSTRAINT movies_title_length
        CHECK (LENGTH(TRIM(title)) BETWEEN 1 AND 200)
);

-- Copy existing movie titles without duplicates.
INSERT INTO movies (title)
SELECT DISTINCT movie_title FROM reviews;

-- Create a separate table for AI predictions.
CREATE TABLE predictions (
    id BIGSERIAL PRIMARY KEY,
    review_id BIGINT NOT NULL UNIQUE,
    sentiment TEXT NOT NULL
        CHECK (sentiment IN ('positive', 'neutral', 'negative')),
    model_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT predictions_model_version_length
        CHECK (LENGTH(TRIM(model_version)) BETWEEN 1 AND 100)
);

-- Preserve existing predictions before changing reviews.
INSERT INTO predictions (review_id, sentiment, model_version)
SELECT id, sentiment, model_version FROM reviews;

-- Link each existing review to its movie.
ALTER TABLE reviews ADD COLUMN movie_id BIGINT;

UPDATE reviews AS r
SET movie_id = m.id
FROM movies AS m
WHERE r.movie_title = m.title;

-- Require every review to reference an existing movie.
ALTER TABLE reviews
    ALTER COLUMN movie_id SET NOT NULL,
    ADD CONSTRAINT reviews_movie_fk
        FOREIGN KEY (movie_id) REFERENCES movies(id);

-- Remove duplicated movie and prediction fields.
ALTER TABLE reviews
    DROP COLUMN movie_title,
    DROP COLUMN sentiment,
    DROP COLUMN model_version;

-- Link each prediction to its review.
ALTER TABLE predictions
    ADD CONSTRAINT predictions_review_fk
        FOREIGN KEY (review_id) REFERENCES reviews(id);

-- Enforce field lengths at the database level.
ALTER TABLE reviews
    ADD CONSTRAINT reviews_external_id_length
        CHECK (LENGTH(TRIM(external_id)) BETWEEN 1 AND 100),
    ADD CONSTRAINT reviews_text_length
        CHECK (LENGTH(TRIM(review_text)) BETWEEN 1 AND 1000);

-- Create indexes for common searches.
CREATE INDEX idx_reviews_movie_id ON reviews (movie_id);
CREATE INDEX idx_predictions_sentiment ON predictions (sentiment);

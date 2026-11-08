CREATE TABLE IF NOT EXISTS tickets (
    id BIGSERIAL PRIMARY KEY,
    text TEXT NOT NULL CHECK (char_length(text) BETWEEN 1 AND 1000),
    category TEXT NOT NULL CHECK (category IN ({categories})),
    model_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

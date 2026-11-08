# Review sentiment classifier

Trained for the movie-review board. The service loads `services/ai/artifact.json` at startup. Retrain with `python -m services.ai.train` from the repository root.

- **Method:** multinomial Naive Bayes over lowercase English word counts, with add-one smoothing. The movie title is not a feature and is not used as a label.
- **Data:** 42 synthetic reviews in `services/ai/training.csv`, 14 for each of `positive`, `neutral`, and `negative`. The file has `text` and `category` columns only.
- **Split:** `services/ai/eval.csv` has 8 reviews that do not appear in training. Six clear reviews cover every label. Two more reviews are an unseen negation and an unseen mixed-sentiment sentence.
- **Version:** `nb-v2-6aa22689257b`. The `nb-v2-` prefix is this trained artifact. The suffix is the first 12 hexadecimal digits of the SHA-256 hash of `training.csv`.
- **Evaluation:** clear held-out reviews: 6/6. All eight eval reviews, including negation and mixed sentiment: 6/8. See `evidence/ai.md`.
- **Runtime:** Python standard library on CPU. No GPU, model download, paid API, or external dataset.
- **Limitations:** word counts ignore negation, so "not wonderful" is scored like "wonderful" and the negation example is predicted `positive`. A mixed review must be forced into one of the three labels; overlapping positive and negative words make that choice unreliable. The training set is tiny and English-only. Unknown words are ignored. There is no calibrated confidence.
- **Use:** classroom demonstration only. Predictions are suggestions and can be incorrect even when all services work.

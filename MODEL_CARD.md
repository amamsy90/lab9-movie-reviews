# Supplied CPU classifier

This is the starter baseline. Replace this card with details of the model you train for the assignment; see [STUDENT_GUIDE.md](STUDENT_GUIDE.md) for the required training and evaluation work.

- **Method:** multinomial Naive Bayes over lowercase English word counts, with add-one smoothing. Trains at startup from `services/ai/training.csv`.
- **Data:** 24 original synthetic teaching examples, eight per category. Labels and sample inputs are in `project.json`.
- **Version:** `nb-v1-` plus the first 12 hexadecimal digits of the training file's SHA-256 hash. Change the prefix if you change the algorithm.
- **Runtime:** Python standard library; no GPU, model download, paid API, or external dataset required.
- **Limitations:** tiny training set, English-only tokenization, no understanding of negation/context, no calibrated confidence, and forced choice among three labels. Unknown words are ignored; when none are known, priors and a fixed tie order determine the answer. Baseline smoke tests do not establish real-world accuracy.
- **Use:** classroom demonstration only. Predictions are suggestions and can be incorrect even when all services work.

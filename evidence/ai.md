# CPU ML microservice: evidence

- API documentation and request/response examples:

  `GET /healthz` returns the loaded artifact version.

  ```json
  {"service": "ai", "status": "ok", "model_version": "nb-v2-6aa22689257b"}
  ```

  `POST /predict` with `{"text": "Wonderful acting and brilliant visuals made a delightful film"}` returns:

  ```json
  {"category": "positive", "model_version": "nb-v2-6aa22689257b"}
  ```

  Labels are `positive`, `neutral`, or `negative`. Empty text, blank text, and text longer than 1000 characters return HTTP 400 with `{"error": "Enter between 1 and 1000 characters."}`. The movie title is not sent as a label. The same title with different review text gets different predictions: "Moon Garden was wonderful delightful and excellent" is `positive`, and "Moon Garden was awful boring and dreadful" is `negative`.

- Test commands and results:

  From the repository root: `python -m unittest discover -s tests -v`

  Result on 8 November 2026: 26 tests, 18 passed, 8 skipped. The skipped tests are the PostgreSQL checks, which need a database. The sentiment tests cover artifact loading, clear held-out labels, the negation and mixed misses, a shared movie title with opposite review text, a successful prediction, a 1000-character input, and empty or oversized input.

- Build/start commands and configuration names:

  Train and write the artifact: `python -m services.ai.train`

  Start locally from the repository root: `python -m services.ai.app`. `PORT` defaults to `8000`. This machine already had another program on port 8000, so the local process uses `PORT=8010`.

  Container: `docker build -f services/ai/Dockerfile -t lab9-ai .` then `docker run --rm -p 8010:8000 lab9-ai`. The image copies `services/ai`, including `artifact.json`. No environment variables are required. The process listens on `0.0.0.0` and `PORT`.

- Deployed service check (time and result):

  Local process, 8 November 2026: `GET http://127.0.0.1:8010/healthz` returned `ok` with `model_version` `nb-v2-6aa22689257b`. A public HTTPS deployment is still to be done.

- Prepared or extended labeled data and held-out split:

  Extended the starter file from 24 to 42 synthetic reviews, 14 per label, in `services/ai/training.csv`. Columns are `text` and `category` only. Held-out file `services/ai/eval.csv` has 8 reviews that are not in the training file: 6 clear reviews (2 per label) plus one negation review and one mixed-sentiment review.

- Training code changes, reproducible command, parameters, and resulting artifact/version:

  `services/ai/train.py` fits a multinomial Naive Bayes model with add-one smoothing on lowercase English word counts, then writes `services/ai/artifact.json`. `services/ai/app.py` loads that artifact when the process starts and does not retrain on launch. Command: `python -m services.ai.train`. Version: `nb-v2-6aa22689257b`.

- Evaluation command, expected/actual labels, accuracy, and observed limitation:

  The same command prints the eval table. Clear held-out accuracy is 6/6. Accuracy on all 8 eval rows is 6/8.

  | Kind | Expected | Actual | Text |
  | --- | --- | --- | --- |
  | clear | positive | positive | Wonderful acting and brilliant visuals made a delightful film |
  | clear | neutral | neutral | The film follows two characters in a coastal town |
  | clear | negative | negative | Awful acting and boring dialogue made a dreadful movie |
  | clear | positive | positive | Outstanding performances and a wonderful story made me love this film |
  | clear | neutral | neutral | The film contains six chapters and was filmed in one town |
  | clear | negative | negative | I hated the awful pacing and the dreadful performances |
  | negation | negative | positive | The movie was not wonderful and not delightful |
  | mixed | negative | positive | Wonderful brilliant and delightful acting but the story was boring |

  Limitation: the classifier counts words and has no negation feature, so "not wonderful" is treated like "wonderful". It also cannot return a mixed label, so a review with both positive and negative words is forced into whichever side has the stronger count.

- Deployed model artifact/version and inference checks:

  Artifact: `services/ai/artifact.json`. Version: `nb-v2-6aa22689257b`. Local `POST /predict` for the first clear positive review returned `positive` with that version.

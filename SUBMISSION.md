# Movie review board: submission

- Team: team-01 (Ghaith / GateKG, Aishah / amamsy90, Maitha / maitha22)
- Public HTTPS URL: https://lab9-movie-reviews.onrender.com
- GitHub repository URL: https://github.com/amamsy90/lab9-movie-reviews
- Full deployed commit SHA (record after the final merge): `d22ff576d1af93017981ca14aaac8ec67c6d9ad0` (`main` after pull request #8). The live services were already running that application code; #8 adds tests and data evidence only. The data service was switched to `main` at `e6f2e14618460ed97627797040d473aae5c767ba`.
- Checking window: not written down in the repository. Keep the website and this private repository available until the instructor closes checking.

| Component | Owner | Evidence | Implementation PR | Integration/release PR | Review links |
| --- | --- | --- | --- | --- | --- |
| W: `web` | Ghaith | [web](evidence/web.md) | https://github.com/amamsy90/lab9-movie-reviews/pull/4 | W2 was not opened | https://github.com/amamsy90/lab9-movie-reviews/pull/4#pullrequestreview-5817327026 |
| I: `reviews` | Ghaith | [reviews](evidence/reviews.md) | https://github.com/amamsy90/lab9-movie-reviews/pull/2 | I2 was not opened | https://github.com/amamsy90/lab9-movie-reviews/pull/2#pullrequestreview-5817258978 |
| A: `ai` | Aishah | [ai](evidence/ai.md) | https://github.com/amamsy90/lab9-movie-reviews/pull/3 | https://github.com/amamsy90/lab9-movie-reviews/pull/6 | https://github.com/amamsy90/lab9-movie-reviews/pull/3#pullrequestreview-5817206825 and https://github.com/amamsy90/lab9-movie-reviews/pull/6#pullrequestreview-5817350773 |
| D: PostgreSQL + `data` | Maitha | [data](evidence/data.md) | https://github.com/amamsy90/lab9-movie-reviews/pull/5 | https://github.com/amamsy90/lab9-movie-reviews/pull/8 | https://github.com/amamsy90/lab9-movie-reviews/pull/5#pullrequestreview-5817385613 and https://github.com/amamsy90/lab9-movie-reviews/pull/8#pullrequestreview-5909911308 |

The shared contract is pull request #1. It has no approving review. Pull request #7 is the SSL connection used by the live database; Ghaith approved it at https://github.com/amamsy90/lab9-movie-reviews/pull/7#pullrequestreview-5909801334.

Run the [examiner's workflow in PROJECT.md](PROJECT.md). Record input, expected/actual result for each step, check time, and checker:

Checked by Aishah on 15 November 2026, about 12:51 Asia/Dubai, through https://lab9-movie-reviews.onrender.com. Fresh CSV columns were `review_id`, `movie_title`, `review_text`.

1. Import five new reviews for *Silver Harbor* and *Lantern Fields*. Expected: five added. Actual: `{"added": 5, "duplicates": 0, "skipped": 0}`. Saved sentiments, all model `nb-v2-6aa22689257b`: exam-harbor-1 positive, exam-harbor-2 neutral, exam-harbor-3 negative, exam-lantern-1 positive, exam-lantern-2 negative.
2. Filter *Silver Harbor* to negative. Expected: the dreadful-movie review only. Actual: one row, `exam-harbor-3`, sentiment negative. Counts: Silver Harbor 1 positive, 1 neutral, 1 negative, total 3. Lantern Fields 1 positive, 0 neutral, 1 negative, total 2.
3. Reimport the same CSV. Expected: no new rows and the same counts. Actual: `{"added": 0, "duplicates": 5, "skipped": 0}`. Silver Harbor stayed 1 / 1 / 1.

Final service status and repository access check:

On 15 November 2026 the four health checks returned `ok`: web, reviews, ai (`nb-v2-6aa22689257b`), and data. The movie list included the saved titles. The repository is private, so the examiner still needs a GitHub collaborator invite before they can open the code.

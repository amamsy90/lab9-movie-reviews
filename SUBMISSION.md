# Movie review board: submission

- Team: team-01 (Ghaith / GateKG, Aishah / amamsy90, Maitha / maitha22)
- Public HTTPS URL: https://lab9-movie-reviews.onrender.com
- GitHub repository URL: https://github.com/amamsy90/lab9-movie-reviews
- Full deployed commit SHA (record after the final merge): `a1e06d1b736a238fae15475bbc7aef68d341d227`, the merge of pull request #11 and the last code change on `main`. All four services (`web`, `reviews`, `ai`, `data`) are deployed on Render from this commit. Later commits change documentation only.
- Checking window: not announced in the repository. Confirm the dates with the instructor. The free Render database expires on 8 December 2026, so it has to stay available through that window.

| Component | Owner | Evidence | Implementation PR | Integration/release PR | Review links |
| --- | --- | --- | --- | --- | --- |
| W: `web` | Ghaith | [web](evidence/web.md) | https://github.com/amamsy90/lab9-movie-reviews/pull/4 | https://github.com/amamsy90/lab9-movie-reviews/pull/11 | https://github.com/amamsy90/lab9-movie-reviews/pull/4#pullrequestreview-5817327026 |
| I: `reviews` | Ghaith | [reviews](evidence/reviews.md) | https://github.com/amamsy90/lab9-movie-reviews/pull/2 | https://github.com/amamsy90/lab9-movie-reviews/pull/10 | https://github.com/amamsy90/lab9-movie-reviews/pull/2#pullrequestreview-5817258978 and https://github.com/amamsy90/lab9-movie-reviews/pull/10#pullrequestreview-5909977036 |
| A: `ai` | Aishah | [ai](evidence/ai.md) | https://github.com/amamsy90/lab9-movie-reviews/pull/3 | https://github.com/amamsy90/lab9-movie-reviews/pull/6 | https://github.com/amamsy90/lab9-movie-reviews/pull/3#pullrequestreview-5817206825 and https://github.com/amamsy90/lab9-movie-reviews/pull/6#pullrequestreview-5817350773 |
| D: PostgreSQL + `data` | Maitha | [data](evidence/data.md) | https://github.com/amamsy90/lab9-movie-reviews/pull/5 | https://github.com/amamsy90/lab9-movie-reviews/pull/8 | https://github.com/amamsy90/lab9-movie-reviews/pull/5#pullrequestreview-5817385613 and https://github.com/amamsy90/lab9-movie-reviews/pull/8#pullrequestreview-5909911308 |

The shared contract is pull request #1. It has no approving review. Pull request #7 is the SSL connection used by the live database; Ghaith approved it at https://github.com/amamsy90/lab9-movie-reviews/pull/7#pullrequestreview-5909801334.

Run the [examiner's workflow in PROJECT.md](PROJECT.md). Record input, expected/actual result for each step, check time, and checker:

Checked by Aishah on 15 November 2026, about 12:51 Asia/Dubai, from outside the classroom network, through the public site https://lab9-movie-reviews.onrender.com.

Input CSV:

```csv
review_id,movie_title,review_text
exam-harbor-1,Silver Harbor,Wonderful acting and brilliant visuals made a delightful film
exam-harbor-2,Silver Harbor,The film follows two characters in a coastal town
exam-harbor-3,Silver Harbor,Awful acting and boring dialogue made a dreadful movie
exam-lantern-1,Lantern Fields,Outstanding performances and a wonderful story made me love this film
exam-lantern-2,Lantern Fields,I hated the awful pacing and the dreadful performances
```

1. Import. Expected: five added. Actual: `{"added": 5, "duplicates": 0, "skipped": 0}`. Saved sentiments, all model `nb-v2-6aa22689257b`: exam-harbor-1 positive, exam-harbor-2 neutral, exam-harbor-3 negative, exam-lantern-1 positive, exam-lantern-2 negative.
2. Filter *Silver Harbor* to negative. Expected: the dreadful-movie review only. Actual: one row, `exam-harbor-3`, sentiment negative. Counts at that time: Silver Harbor 1 positive, 1 neutral, 1 negative, total 3. Lantern Fields 1 positive, 0 neutral, 1 negative, total 2.
3. Refresh, then reimport the same CSV. A new request still returned those saved reviews. Reimport returned `{"added": 0, "duplicates": 5, "skipped": 0}`, and Silver Harbor stayed 1 / 1 / 1. Teammates added more reviews later, so a later refresh shows a larger count.

Final service status and repository access check:

On 15 November 2026 the four health checks returned `ok`: web, reviews, ai (`nb-v2-6aa22689257b`), and data. The movie list included the saved titles. The GitHub repository is public, so an examiner can open the code without a collaborator invite.

# PostgreSQL DATABASE and Data Service: D1/D2 evidence

Owner: Maitha (`maitha22`). Recorded 15 November 2026 (Asia/Dubai).

D1 implementation was merged in [PR #5](https://github.com/amamsy90/lab9-movie-reviews/pull/5).
D2 adds integration/regression tests and this evidence; it does not redesign the
database or modify application services or applied SQL migrations.

The D2 branch was fast-forwarded to main commit
`e6f2e14618460ed97627797040d473aae5c767ba`, which already contains
[PR #7](https://github.com/amamsy90/lab9-movie-reviews/pull/7). Its SSL/timeout
changes are inherited from main, not duplicated in D2. No commit or stash was
needed; existing uncommitted tests and the SQL backup were preserved.

## Database design and migrations

Only `data` accesses PostgreSQL. Reviews and Web use HTTP.

- `movies`: unique title, primary key, nonblank title limited to 200 characters.
- `reviews`: primary key, unique nonblank external ID (up to 100 characters),
  review text (up to 1000 characters), movie foreign key, and creation timestamp.
- `predictions`: primary key, unique review foreign key, a sentiment constrained
  to `positive`, `neutral`, or `negative`, and nonblank model version (up to 100
  characters). Each review saved through the API gets one prediction.
- Movie and sentiment indexes support the review queries. API joins preserve
  the agreed flat review response despite the normalized tables.

Migration 003 creates the initial movie-review table. Migration 004 copies movie
titles and prediction values into related tables, retains review IDs and review
timestamps, and establishes foreign keys. The populated 003-to-004 regression
checks every original review, sentiment, model version, ID, and timestamp; it
also checks repeat migration and subsequent insertion. There was no separate
prediction timestamp in schema 003; the test does not claim preservation of one.

The existing migration runner uses transactions, an advisory lock, and a
checksum ledger. Applied migration files were not edited. Tests cover failed
migration rollback, concurrent startup, and rejection of rewritten migrations.

## Verified API examples

Contract: [API_CONTRACT.md](../API_CONTRACT.md). These examples were exercised
against isolated local PostgreSQL through real Data HTTP handlers, not Render.
Generated IDs and timestamps are asserted by tests rather than invented here.

`POST /reviews` with this JSON returns HTTP 201 and the supplied fields plus an
integer `id` and timezone-aware `created_at`:

```json
{
  "external_id": "review-1",
  "movie_title": "Moon Garden",
  "review_text": "A wonderful fictional film.",
  "sentiment": "positive",
  "model_version": "test-model-v2"
}
```

| Request or condition | Verified response |
| --- | --- |
| `GET /reviews/by-external-id/review-1` after creation | 200; same complete stored review |
| Repeated POST using that external ID | 409, `{"error":"Review ID already exists."}`; original unchanged |
| Unknown external ID | 404, `{"error":"Review not found."}` |
| POST with sentiment `mixed` | 400, `{"error":"Invalid sentiment."}`; no writes |
| `GET /movies` after two-movie import | 200, `["Moon Garden","Silver Harbor"]` |
| `GET /reviews?movie_title=Moon%20Garden` | 200; only that movie's reviews |
| `GET /reviews?sentiment=positive` | 200; only positive reviews |
| `GET /reviews?movie_title=Moon%20Garden&sentiment=negative` | 200; both filters applied |
| `GET /reviews?movie_title=Unknown&all=true` | 200, `[]` |
| `GET /reviews?movie_title=Moon%20Garden&all=true` after 105-review import | All 105 reviews; ordinary list limited to 100 |
| `GET /healthz` with database available | 200, `{"service":"data","status":"ok"}` |
| Synthetic database connection failure | Data health returns 503 with a sanitized error |

Titles such as `"  Moon   Garden "` normalize to `"Moon Garden"` on import,
creation, and filtering. Encoded external IDs containing spaces, slashes, `#`,
and `?` survive lookup and reimport.

## Reviews -> Data -> PostgreSQL integration

`tests/test_database.py` contains 28 database/integration tests: eight existing
baseline tests, ten review/schema/migration regressions, and ten real HTTP
pipeline tests. Each test owns a temporary schema in a disposable database.

The new pipeline tests use the actual Reviews and Data handlers over HTTP and
actual PostgreSQL. Only AI predictions use the existing controlled HTTP double
(`test-v1`); these are not trained-model evaluation results.

Verified outcomes:

- New CSV rows persist their text, normalized title, sentiment, model version,
  ID, and timestamp. Multiple reviews can share a movie.
- Identical reimports add nothing, do not call AI again, and preserve all three
  tables. Conflicting reuse of an ID is skipped without changing the original.
- Individual and combined filters work; unknown movies have zero counts.
- Importing 105 reviews in batches of at most 20 yields 35 positive, 35 neutral,
  and 35 negative reviews in counts, despite the ordinary 100-row list limit.
- Twenty-row files are accepted; 21-row files are rejected. Exactly 1 MiB is
  accepted; a Content-Length of 1 MiB + 1 returns 413 before reading the body.
- Invalid CSV is rejected; invalid rows are skipped while valid rows are saved.
- AI 503 responses cause skipped rows, and a later AI failure preserves earlier
  saved rows. A database failure injected at the connection boundary propagates
  through the real Data HTTP handler and yields appropriate Reviews errors.
- Direct SQL tests enforce uniqueness, field checks, and foreign keys. A
  test-only prediction constraint forces the final insert to fail; all movie,
  review, and prediction writes roll back atomically, and a later valid save works.

## Persistent storage and actual container restarts

`tests/test_persistence.py` is an opt-in Docker regression. It creates a unique,
labelled PostgreSQL volume and separate PostgreSQL, Data, Reviews, Web, and AI
test-double containers. Before startup it verifies network isolation, absence
of published ports, ownership labels, and mounts. Application source is mounted
read-only; no Docker socket or existing database volumes are mounted.

Four reviews (`persist-1` through `persist-4`) were imported through Reviews.
The test records and compares complete API objects, including internal IDs,
external IDs, titles, text, sentiments, model versions, and timestamps.

| Movie | Positive | Neutral | Negative | Total |
| --- | ---: | ---: | ---: | ---: |
| Moon Garden | 1 | 1 | 1 | 3 |
| Silver Harbor | 1 | 0 | 0 | 1 |

All application containers were stopped; PostgreSQL was restarted with the
same dedicated volume; then applications were started again. Changed container
startup timestamps prove actual restarts. Data ran its normal migration check.
Every recorded object and count remained identical. Reimport through both
Reviews and Web returned **0 added, 4 duplicates, 0 skipped**, with no changes.

Web `/api/reviews`, `/api/movies`, and `/api/counts` returned the same stored
data after restart. This is an **HTTP-level Web check, not an actual browser
refresh**. The new persistence test passed before updating main (22.904s); the
final rerun against the updated base is recorded below.

Only newly created, ownership-verified test resources are removed by this
regression. The team's Compose storage and backup are never used.

## Build, configuration, and safe test commands

The Data Dockerfile runs `python -m services.data.app`, which applies pending
migrations before starting HTTP. It listens on `0.0.0.0` and `PORT` (default 8000).
Compose connects Data to `db` and stores PostgreSQL files in its named `database`
volume. The D2 checks did not start or modify that normal Compose environment.

| Data variable | Meaning |
| --- | --- |
| `DB_HOST`, `DB_PORT` | PostgreSQL host and port (defaults `db`, `5432`) |
| `DB_NAME`, `DB_USER` | Database and user (default `helpdesk`) |
| `DB_PASSWORD` | Required secret; never record a real value in evidence |
| `DB_SSLMODE` | Added by merged PR #7; default `prefer`; use `require` to enforce TLS on Render |
| `PORT` | HTTP listening port |

The current connection timeout is 10 seconds; statement timeout is 3000 ms.
This code uses individual `DB_*` settings, not `DATABASE_URL`. Reviews and Web
need a reachable `DATA_URL`; Web also needs `REVIEWS_URL`.

The persistence regression requires the cached test image. If preparing a new
machine, build it first (setup instruction, not a claim of a new build here):

```sh
docker build -t lab9-movie-reviews-team-data -f services/data/Dockerfile .
```

Exact persistence rerun command:

```sh
TEST_PERSISTENCE=1 PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p test_persistence.py -v
```

The ordinary database suite is enabled with `TEST_DATABASE=1` only against an
explicitly disposable database. Final run used a uniquely named `postgres:17`
container with network disabled, no published ports, and tmpfs data storage.
The following exact runner invocation used a dummy, test-only password; its
database container is temporary and is removed after verification:

```sh
docker run --rm --name lab9-d2-final-suite-cbe192fef578 --network container:lab9-d2-final-pg-cbe192fef578 --read-only --tmpfs /tmp:rw,nosuid,size=64m --mount type=bind,src=/Users/maith/Documents/lab9-movie-reviews-team,dst=/app,readonly --workdir /app -e PYTHONDONTWRITEBYTECODE=1 -e TEST_DATABASE=1 -e DB_HOST=127.0.0.1 -e DB_PORT=5432 -e DB_NAME=d2_final_tests -e DB_USER=d2_test -e DB_PASSWORD=disposable-test-only --entrypoint python lab9-movie-reviews-team-data:latest -B -m unittest discover -s tests -v
```

The Docker persistence test runs separately on the host. It is intentionally
skipped inside the ordinary test runner, which has no Docker socket. Existing
AI model tests in the full suite remain separate from the controlled AI used by
the new storage/integration tests.

### Final verified results after updating from main

Checked locally during Maitha's D2 preparation on 15 November 2026, against
`e6f2e14618460ed97627797040d473aae5c767ba` plus the uncommitted D2 tests:

| Run | Discovered | Passed | Failed/errors | Skipped | Elapsed |
| --- | ---: | ---: | ---: | ---: | ---: |
| Full regression suite with isolated PostgreSQL | 70 | 69 | 0 | 1 | 49.811s |
| Opt-in real-container persistence regression on host | 1 | 1 | 0 | 0 | 22.918s |

The one skip in the full run is the persistence test, which passed separately
on the host. All 28 database/integration tests ran successfully. No application
defects were exposed by these tests. The full run also confirms local non-TLS
PostgreSQL compatibility with the inherited `DB_SSLMODE=prefer` default; it does
not establish a live TLS handshake or test every SSL/timeout environment setting.

`git diff --check` passed. The backup retained SHA-256
`82982cc162c5c18074b4739115cddb4f26a434d1bb1472832f6183d335359f07`.
The persistence regression removed its newly created labelled containers and
volume. The full-suite database had zero remaining test schemas before stopping
and removing its verified test-owned container. No test services were left running.

## Teammate-reported live Render checks

These were performed by **Ghaith (`GateKG`) on 15 November 2026**, not by Maitha
or the D2 local test runner. Source: [PR #7 approval and deployment report](https://github.com/amamsy90/lab9-movie-reviews/pull/7#pullrequestreview-5909801334).

- Ghaith reported `GET https://lab9-data.onrender.com/healthz` returned
  `{"service":"data","status":"ok"}`. The route executes `SELECT 1`, providing
  evidence of a working deployed database connection.
- He reported the website's `/api/movies` returned `["The Demo Film"]`; counts
  for that movie were 1 positive, 0 neutral, and 0 negative, read through Data.
- He reported successful PR #7 CI, including Compose migration/API checks and
  restart smoke checks, and that live Data deployed from `fix/render-db-ssl`.

Those reported checks were not repeated against production during D2. They do
not establish the deployed `DB_SSLMODE` value, certificate verification, a live
browser refresh, a live write/reimport check, or the final deployed main SHA.

## Remaining release checks and known inherited follow-ups

- Obtain an actual browser-refresh check against persisted reviews; do not
  substitute the verified HTTP checks above.
- Confirm Render `DB_SSLMODE=require` and record configuration confirmation
  without credentials. The deployed value is not available in the cited report.
- Coordinate the follow-ups explicitly retained in PR #7: preserve or document
  `PGSSLMODE` precedence, align the 10-second connection timeout with shorter
  callers/health checks, and add SSL/timeout argument regression coverage.
  D2 does not independently alter these application settings.
- Coordinate updating the API configuration table for `DB_SSLMODE` with its
  owner; this D2 change documents it here without editing teammates' files.
- The Data deployment source was moved from `fix/render-db-ssl` to `main` on
  15 November 2026. Render redeployed commit `e6f2e14618460ed97627797040d473aae5c767ba`
  after the branch change, and `GET /healthz` returned ok. The examiner workflow
  is recorded in `SUBMISSION.md`. Current `main` is later than that deploy.
  The SHA that all four services actually run still has to be written down
  after the final merge and redeploy.

No production credentials or databases were accessed. No normal Compose
containers or existing Docker volumes were changed. The SQL backup is excluded
from the D2 change. No commit, push, PR creation, merge commit, or deployment was
performed while preparing this evidence.

"""Optional PostgreSQL integration tests; every test owns a temporary schema.

Run with TEST_DATABASE=1 and the data service's DB_* variables pointing at a
throwaway database. Compose CI runs these inside the data image.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import csv
import io
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from uuid import uuid4

from common import Handler
from project import CATEGORIES
from services.ai.app import AI
from services.web import app as web
from services.reviews import app as reviews
from test_app import server
from test_reviews import FakeAI, Down, call
from tools.smoke import request, smoke

if os.environ.get("TEST_DATABASE") == "1":
    import psycopg
    from psycopg import sql
    from services.data import app as data
    from services.data.migrate import MIGRATIONS, migrate


@unittest.skipUnless(os.environ.get("TEST_DATABASE") == "1", "requires a disposable PostgreSQL database")
class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.original_connect = data.connect
        self.schema = "test_" + uuid4().hex
        with self.original_connect() as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.connect_patch = patch.object(data, "connect", self.connect)
        self.connect_patch.start()
        self.log_patch = patch.object(Handler, "log_message", lambda *args: None)
        self.log_patch.start()

    def tearDown(self):
        self.connect_patch.stop()
        self.log_patch.stop()
        with self.original_connect() as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def connect(self):
        connection = self.original_connect()
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(self.schema)))
        connection.commit()
        return connection

    def migrate(self, directory=None):
        with self.connect() as connection:
            migrate(connection, directory or MIGRATIONS)

    def insert(self, text="Saved before upgrade"):
        with self.connect() as connection:
            return connection.execute(
                "INSERT INTO tickets (text, category, model_version) VALUES (%s, %s, 'test-v1') RETURNING id",
                (text, CATEGORIES[0]),
            ).fetchone()["id"]

    def test_fresh_repeat_and_incremental_migrations_preserve_records(self):
        self.migrate()
        ticket_id = self.insert()
        self.migrate()
        with tempfile.TemporaryDirectory() as folder:
            shutil.copytree(MIGRATIONS, folder, dirs_exist_ok=True)
            Path(folder, "900_add_note.sql").write_text("ALTER TABLE tickets ADD COLUMN note TEXT NOT NULL DEFAULT 'kept';")
            self.migrate(folder)
            self.migrate(folder)
            with self.connect() as connection:
                row = connection.execute("SELECT * FROM tickets WHERE id = %s", (ticket_id,)).fetchone()
                self.assertEqual(row["text"], "Saved before upgrade")
                self.assertEqual(row["note"], "kept")
                self.assertEqual(connection.execute("SELECT count(*) AS n FROM schema_migrations").fetchone()["n"], len(list(Path(folder).glob("*.sql"))))

    def test_upgrade_from_old_schema_without_migration_ledger(self):
        with self.connect() as connection:
            connection.execute(sql.SQL((MIGRATIONS / "001_initial.sql").read_text()).format(
                categories=sql.SQL(", ").join(sql.Literal(c) for c in CATEGORIES)))
        ticket_id = self.insert()
        self.migrate()
        with self.connect() as connection:
            self.assertEqual(connection.execute("SELECT id FROM tickets").fetchone()["id"], ticket_id)
            self.assertEqual(connection.execute("SELECT count(*) AS n FROM schema_migrations").fetchone()["n"], len(list(MIGRATIONS.glob("*.sql"))))

    def test_failed_upgrade_rolls_back_schema_and_ledger(self):
        self.migrate()
        self.insert()
        with tempfile.TemporaryDirectory() as folder:
            shutil.copytree(MIGRATIONS, folder, dirs_exist_ok=True)
            Path(folder, "900_add_note.sql").write_text("ALTER TABLE tickets ADD COLUMN note TEXT;")
            Path(folder, "901_invalid.sql").write_text("THIS IS INVALID SQL;")
            with self.assertRaises(psycopg.Error):
                self.migrate(folder)
        with self.connect() as connection:
            self.assertEqual(connection.execute("SELECT count(*) AS n FROM schema_migrations").fetchone()["n"], len(list(MIGRATIONS.glob("*.sql"))))
            self.assertNotIn("note", connection.execute("SELECT * FROM tickets").fetchone())

    def test_applied_migrations_cannot_be_rewritten(self):
        self.migrate()
        with tempfile.TemporaryDirectory() as folder:
            shutil.copytree(MIGRATIONS, folder, dirs_exist_ok=True)
            Path(folder, "002_ticket_category_index.sql").write_text("SELECT 1;")
            with self.assertRaisesRegex(ValueError, "Applied migration changed"):
                self.migrate(folder)

    def test_concurrent_startups_apply_each_migration_once(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: self.migrate(), range(2)))
        with self.connect() as connection:
            self.assertEqual(connection.execute("SELECT count(*) AS n FROM schema_migrations").fetchone()["n"], len(list(MIGRATIONS.glob("*.sql"))))

    def test_search_filters_and_missing_ids_through_web_and_real_database(self):
        self.migrate()
        with server(data.Data) as data_url, patch.object(web, "DATA_URL", data_url), server(web.Web) as web_url:
            for text, category in (("ACME 100%_ earnings", CATEGORIES[0]),
                                   ("Other filing", CATEGORIES[0]), ("Acme wind", CATEGORIES[1])):
                self.assertEqual(request(data_url + "/tickets", {
                    "text": text, "category": category, "model_version": "test-v1"
                })[0], 201)
            for params, expected in (({"q": "acme", "category": CATEGORIES[1]}, ["Acme wind"]),
                                     ({"q": "100%_"}, ["ACME 100%_ earnings"]),
                                     ({"q": "' OR 1=1 --"}, [])):
                status, rows = request(web_url + "/api/tickets?" + urlencode(params))
                self.assertEqual(status, 200)
                self.assertEqual([row["text"] for row in rows], expected)
            self.assertEqual(request(web_url + "/api/tickets?category=invalid")[0], 400)
            self.assertEqual(request(web_url + "/api/tickets?q=a&q=b")[0], 400)
            status, rows = request(web_url + "/api/tickets")
            self.assertEqual(len(rows), 3)
            self.assertEqual(request(web_url + "/api/tickets/" + str(rows[0]["id"])), (200, rows[0]))
            self.assertEqual(request(web_url + "/api/tickets/99999999"), (404, {"error": "Unknown ticket ID."}))

    def test_real_three_service_baseline_after_migration(self):
        self.migrate()
        with server(data.Data) as data_url, server(AI) as ai_url:
            with patch.object(web, "DATA_URL", data_url), patch.object(web, "AI_URL", ai_url):
                with server(web.Web) as web_url:
                    self.assertIn("PASS", smoke(web_url))

    def test_database_conflicts_and_invalid_data_remain_client_errors(self):
        self.migrate()
        with self.connect() as connection:
            connection.execute("ALTER TABLE tickets ADD CONSTRAINT unique_text UNIQUE (text)")
            connection.execute("ALTER TABLE tickets ADD CONSTRAINT no_reserved CHECK (text <> 'reserved')")
        with server(data.Data) as data_url, patch.object(web, "DATA_URL", data_url), \
                patch.object(web, "AI_URL", data_url), server(web.Web) as web_url:
            payload = {"text": "Duplicate", "category": CATEGORIES[0], "model_version": "test-v1"}
            self.assertEqual(request(data_url + "/tickets", payload)[0], 201)
            # The web route still uses the real data API; only the prediction is a fixture.
            original = web.request_json
            def predict_or_request(url, body=None):
                if url.endswith("/predict"):
                    return {"category": CATEGORIES[0], "model_version": "test-v1"}
                return original(url, body)
            with patch.object(web, "request_json", predict_or_request):
                status, body = request(web_url + "/api/tickets", {"text": "Duplicate"})
                self.assertEqual(status, 409)
                self.assertNotIn("unique_text", body["error"])
                self.assertNotIn("unavailable", body["error"])
                self.assertEqual(request(web_url + "/api/tickets", {"text": "reserved"})[0], 400)
                self.assertEqual(len(request(web_url + "/api/tickets")[1]), 1)

    # Movie-review regressions use the same per-test schema as the baseline.
    def review_payload(self, **changes):
        return {
            "external_id": "review-1", "movie_title": "Moon Garden",
            "review_text": "A wonderful fictional film.",
            "sentiment": "positive", "model_version": "test-model-v2",
            **changes,
        }

    def review_counts(self):
        with self.connect() as connection:
            return tuple(connection.execute(
                sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier(table))
            ).fetchone()["n"] for table in ("movies", "reviews", "predictions"))

    def test_review_create_and_retrieve_preserves_prediction_and_timestamp(self):
        from datetime import datetime
        from urllib.parse import quote

        self.migrate()
        with server(data.Data) as url:
            for index, sentiment in enumerate(("positive", "neutral", "negative")):
                payload = self.review_payload(
                    external_id=f"batch 1/review#{index}?", sentiment=sentiment,
                    model_version=f"test-model-{index}",
                )
                status, saved = request(url + "/reviews", payload)
                self.assertEqual(status, 201)
                self.assertEqual({key: saved[key] for key in payload}, payload)
                self.assertIsInstance(saved["id"], int)
                self.assertIsNotNone(datetime.fromisoformat(saved["created_at"]).tzinfo)
                lookup = url + "/reviews/by-external-id/" + quote(payload["external_id"], safe="")
                self.assertEqual(request(lookup), (200, saved))
                self.assertIn(saved, request(url + "/reviews")[1])
                with self.connect() as connection:
                    row = connection.execute(
                        data.REVIEW_SELECT + " WHERE r.id = %s", (saved["id"],)
                    ).fetchone()
                    self.assertEqual(row["created_at"].isoformat(), saved["created_at"])
                    self.assertEqual(row["sentiment"], sentiment)
                    self.assertEqual(row["model_version"], payload["model_version"])

    def test_review_duplicate_and_conflicting_ids_return_409_without_changes(self):
        self.migrate()
        payload = self.review_payload()
        with server(data.Data) as url:
            status, saved = request(url + "/reviews", payload)
            self.assertEqual(status, 201)
            for repeated in (payload, self.review_payload(
                movie_title="Different Movie", review_text="Different text.",
                sentiment="negative", model_version="other-model",
            )):
                with self.subTest(payload=repeated):
                    self.assertEqual(request(url + "/reviews", repeated),
                                     (409, {"error": "Review ID already exists."}))
                    self.assertEqual(self.review_counts(), (1, 1, 1))
                    self.assertEqual(request(url + "/reviews/by-external-id/review-1"),
                                     (200, saved))

    def test_review_invalid_sentiments_are_rejected_without_writes(self):
        self.migrate()
        with server(data.Data) as url:
            for sentiment in ("mixed", "Positive", "", None, 1, []):
                with self.subTest(sentiment=sentiment):
                    status, body = request(url + "/reviews", self.review_payload(sentiment=sentiment))
                    self.assertEqual(status, 400)
                    self.assertEqual(body, {"error": "Invalid sentiment."})
                    self.assertEqual(self.review_counts(), (0, 0, 0))

    def test_review_movie_title_normalization_reuses_one_movie(self):
        self.migrate()
        with server(data.Data) as url:
            for index, title in enumerate(("  Moon   Garden \t", "Moon Garden")):
                status, saved = request(url + "/reviews", self.review_payload(
                    external_id=f"r{index}", movie_title=title,
                ))
                self.assertEqual(status, 201)
                self.assertEqual(saved["movie_title"], "Moon Garden")
            self.assertEqual(request(url + "/movies"), (200, ["Moon Garden"]))
            query = urlencode({"movie_title": " Moon  Garden "})
            status, rows = request(url + "/reviews?" + query)
            self.assertEqual(status, 200)
            self.assertEqual({row["external_id"] for row in rows}, {"r0", "r1"})
            self.assertEqual(self.review_counts(), (1, 2, 2))

    def test_review_movie_sentiment_and_combined_filters(self):
        self.migrate()
        with server(data.Data) as url:
            for identifier, movie, sentiment in (
                ("a", "Moon Garden", "positive"), ("b", "Moon Garden", "neutral"),
                ("c", "Silver Harbor", "positive"), ("d", "Silver Harbor", "negative"),
            ):
                self.assertEqual(request(url + "/reviews", self.review_payload(
                    external_id=identifier, movie_title=movie, sentiment=sentiment,
                ))[0], 201)
            for filters, expected in (
                ({}, {"a", "b", "c", "d"}),
                ({"movie_title": "Moon Garden"}, {"a", "b"}),
                ({"sentiment": "positive"}, {"a", "c"}),
                ({"movie_title": "Silver Harbor", "sentiment": "negative"}, {"d"}),
                ({"movie_title": "Moon Garden", "sentiment": "negative"}, set()),
                ({"movie_title": "Unknown"}, set()),
            ):
                with self.subTest(filters=filters):
                    status, rows = request(url + "/reviews?" + urlencode(filters))
                    self.assertEqual(status, 200)
                    self.assertEqual({row["external_id"] for row in rows}, expected)
            self.assertEqual(request(url + "/movies"), (200, ["Moon Garden", "Silver Harbor"]))

    def test_review_empty_results_and_invalid_queries(self):
        self.migrate()
        with server(data.Data) as url:
            for path in ("/reviews", "/movies", "/reviews?movie_title=Unknown&all=true"):
                self.assertEqual(request(url + path), (200, []))
            self.assertEqual(request(url + "/reviews/by-external-id/missing"),
                             (404, {"error": "Review not found."}))
            for query in ("all=true", "all=invalid", "sentiment=mixed",
                          "sentiment=positive&sentiment=negative"):
                with self.subTest(query=query):
                    self.assertEqual(request(url + "/reviews?" + query)[0], 400)

    def test_review_all_retrieval_exceeds_default_100_limit(self):
        self.migrate()
        with server(data.Data) as url:
            expected = {}
            for index in range(105):
                status, saved = request(url + "/reviews", self.review_payload(
                    external_id=f"bulk-{index}",
                    sentiment=("positive", "neutral", "negative")[index % 3],
                ))
                self.assertEqual(status, 201)
                expected[saved["external_id"]] = saved
            self.assertEqual(request(url + "/reviews", self.review_payload(
                external_id="other", movie_title="Other Movie",
            ))[0], 201)
            query = urlencode({"movie_title": "Moon Garden"})
            status, limited = request(url + "/reviews?" + query)
            self.assertEqual(status, 200)
            self.assertEqual(len(limited), 100)
            self.assertEqual(limited, sorted(expected.values(), key=lambda row: row["id"], reverse=True)[:100])
            status, complete = request(url + "/reviews?" + query + "&all=true")
            self.assertEqual(status, 200)
            self.assertEqual(len(complete), 105)
            self.assertEqual({row["external_id"]: row for row in complete}, expected)
            status, positive = request(url + "/reviews?" + query + "&all=true&sentiment=positive")
            self.assertEqual(status, 200)
            self.assertEqual({row["external_id"]: row for row in positive},
                             {key: row for key, row in expected.items() if row["sentiment"] == "positive"})

    def test_review_database_constraints_and_foreign_keys(self):
        self.migrate()
        with server(data.Data) as url:
            self.assertEqual(request(url + "/reviews", self.review_payload())[0], 201)
        with self.connect() as connection:
            review = connection.execute("SELECT * FROM reviews").fetchone()
            movie_id, review_id = review["movie_id"], review["id"]
            cases = (
                (psycopg.errors.UniqueViolation, "INSERT INTO movies (title) VALUES (%s)", ("Moon Garden",)),
                (psycopg.errors.CheckViolation, "INSERT INTO movies (title) VALUES (%s)", (" ",)),
                (psycopg.errors.CheckViolation, "INSERT INTO movies (title) VALUES (%s)", ("x" * 201,)),
                (psycopg.errors.UniqueViolation,
                 "INSERT INTO reviews (movie_id, external_id, review_text) VALUES (%s, %s, %s)",
                 (movie_id, "review-1", "Other text")),
                (psycopg.errors.CheckViolation, "UPDATE reviews SET external_id = %s WHERE id = %s", (" ", review_id)),
                (psycopg.errors.CheckViolation, "UPDATE reviews SET external_id = %s WHERE id = %s", ("x" * 101, review_id)),
                (psycopg.errors.CheckViolation, "UPDATE reviews SET review_text = %s WHERE id = %s", (" ", review_id)),
                (psycopg.errors.CheckViolation, "UPDATE reviews SET review_text = %s WHERE id = %s", ("x" * 1001, review_id)),
                (psycopg.errors.NotNullViolation, "UPDATE reviews SET movie_id = NULL WHERE id = %s", (review_id,)),
                (psycopg.errors.ForeignKeyViolation, "UPDATE reviews SET movie_id = %s WHERE id = %s", (-1, review_id)),
                (psycopg.errors.ForeignKeyViolation, "UPDATE predictions SET review_id = %s WHERE review_id = %s", (-1, review_id)),
                (psycopg.errors.CheckViolation, "UPDATE predictions SET sentiment = %s WHERE review_id = %s", ("mixed", review_id)),
                (psycopg.errors.NotNullViolation, "UPDATE predictions SET sentiment = NULL WHERE review_id = %s", (review_id,)),
                (psycopg.errors.CheckViolation, "UPDATE predictions SET model_version = %s WHERE review_id = %s", (" ", review_id)),
                (psycopg.errors.CheckViolation, "UPDATE predictions SET model_version = %s WHERE review_id = %s", ("x" * 101, review_id)),
                (psycopg.errors.UniqueViolation,
                 "INSERT INTO predictions (review_id, sentiment, model_version) VALUES (%s, %s, %s)",
                 (review_id, "neutral", "another-model")),
                (psycopg.errors.ForeignKeyViolation, "DELETE FROM movies WHERE id = %s", (movie_id,)),
                (psycopg.errors.ForeignKeyViolation, "DELETE FROM reviews WHERE id = %s", (review_id,)),
            )
            for error, statement, parameters in cases:
                with self.subTest(statement=statement, parameters=parameters):
                    # A savepoint rolls back only this intentional constraint violation.
                    with self.assertRaises(error):
                        with connection.transaction():
                            connection.execute(statement, parameters)
        self.assertEqual(self.review_counts(), (1, 1, 1))

    def test_review_failed_prediction_insert_rolls_back_all_tables(self):
        self.migrate()
        with self.connect() as connection:
            # Test-only fault at the final insert, after movie and review insertion.
            connection.execute("ALTER TABLE predictions ADD CONSTRAINT test_reject_version "
                               "CHECK (model_version <> 'force-failure')")
        with server(data.Data) as url:
            payload = self.review_payload(model_version="force-failure")
            status, body = request(url + "/reviews", payload)
            self.assertEqual(status, 400)
            self.assertNotIn("test_reject_version", body["error"])
            self.assertEqual(self.review_counts(), (0, 0, 0))
            self.assertEqual(request(url + "/reviews/by-external-id/review-1")[0], 404)
            # The failed request did not reserve the external ID or poison later saves.
            self.assertEqual(request(url + "/reviews", self.review_payload())[0], 201)
            self.assertEqual(self.review_counts(), (1, 1, 1))

    def test_migration_004_preserves_populated_003_reviews(self):
        from datetime import datetime, timezone

        with tempfile.TemporaryDirectory() as folder:
            for path in sorted(MIGRATIONS.glob("*.sql")):
                if path.name.split("_", 1)[0] <= "003":
                    shutil.copy2(path, folder)
            self.migrate(folder)
        with self.connect() as connection:
            for index, (movie, sentiment) in enumerate((
                ("Moon Garden", "positive"), ("Moon Garden", "neutral"),
                ("Silver Harbor", "negative"),
            )):
                connection.execute(
                    "INSERT INTO reviews (external_id, movie_title, review_text, sentiment, "
                    "model_version, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                    (f"old-{index}", movie, f"Existing review {index}", sentiment,
                     f"old-model-{index}", datetime(2025, 1, index + 1, 12, 34, 56, 123456, tzinfo=timezone.utc)),
                )
            before = connection.execute("SELECT * FROM reviews ORDER BY id").fetchall()
        self.migrate()
        self.migrate()  # Repeated startup must not duplicate migrated data.
        with self.connect() as connection:
            after = connection.execute(data.REVIEW_SELECT + " ORDER BY r.id").fetchall()
            self.assertEqual(after, before)
            self.assertEqual(connection.execute("SELECT title FROM movies ORDER BY title").fetchall(),
                             [{"title": "Moon Garden"}, {"title": "Silver Harbor"}])
            predictions = connection.execute(
                "SELECT review_id, sentiment, model_version FROM predictions ORDER BY review_id"
            ).fetchall()
            self.assertEqual(predictions, [
                {"review_id": row["id"], "sentiment": row["sentiment"], "model_version": row["model_version"]}
                for row in before
            ])
            self.assertEqual(connection.execute(
                "SELECT count(*) AS n FROM schema_migrations WHERE version = %s",
                ("004_normalize_reviews.sql",),
            ).fetchone()["n"], 1)
        with server(data.Data) as url:
            for row in before:
                self.assertEqual(request(url + "/reviews/by-external-id/" + row["external_id"]),
                                 (200, {**row, "created_at": row["created_at"].isoformat()}))
            status, saved = request(url + "/reviews", self.review_payload(external_id="after-upgrade"))
            self.assertEqual(status, 201)
            self.assertGreater(saved["id"], max(row["id"] for row in before))

    @contextmanager
    def running_review_pipeline(self, ai_handler=FakeAI):
        """Real HTTP Reviews -> Data -> PostgreSQL; only AI is a test double."""
        self.migrate()
        FakeAI.calls = 0
        with server(data.Data) as data_url, server(ai_handler) as ai_url:
            with patch.object(reviews, "DATA_URL", data_url), patch.object(reviews, "AI_URL", ai_url):
                with server(reviews.Reviews) as reviews_url:
                    yield reviews_url, data_url

    def review_csv(self, rows):
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(("review_id", "movie_title", "review_text"))
        writer.writerows(rows)
        return output.getvalue().encode("utf-8")

    def review_snapshot(self):
        with self.connect() as connection:
            return {table: connection.execute(
                sql.SQL("SELECT * FROM {} ORDER BY id").format(sql.Identifier(table))
            ).fetchall() for table in ("movies", "reviews", "predictions")}

    def test_reviews_pipeline_import_filters_and_counts(self):
        from datetime import datetime

        rows = [
            ("batch 1/r#1?x", "  Moon   Garden \t", "Wonderful acting"),
            ("r2", "Moon Garden", "A film about a coastal town"),
            ("r3", "Moon Garden", "Awful dialogue"),
            ("r4", "Silver Harbor", "Wonderful scenery"),
        ]
        with self.running_review_pipeline() as (url, data_url):
            status, result = call(url + "/imports", self.review_csv(rows))
            self.assertEqual(status, 200)
            self.assertEqual((result["added"], result["duplicates"], result["skipped"]), (4, 0, 0))
            self.assertEqual([entry["status"] for entry in result["rows"]], ["added"] * 4)
            self.assertEqual(FakeAI.calls, 4)
            self.assertEqual(self.review_counts(), (2, 4, 4))
            status, stored = request(data_url + "/reviews")
            self.assertEqual(status, 200)
            stored = {row["external_id"]: row for row in stored}
            for (identifier, title, text), label in zip(rows, ("positive", "neutral", "negative", "positive")):
                saved = stored[identifier]
                self.assertEqual(saved["movie_title"], " ".join(title.split()))
                self.assertEqual(saved["review_text"], text)
                self.assertEqual(saved["sentiment"], label)
                self.assertEqual(saved["model_version"], "test-v1")
                self.assertIsNotNone(datetime.fromisoformat(saved["created_at"]).tzinfo)
            with self.connect() as connection:
                joined = connection.execute(data.REVIEW_SELECT).fetchall()
                self.assertEqual({row["external_id"]: {
                    **row, "created_at": row["created_at"].isoformat()
                } for row in joined}, stored)
            for filters, expected in (
                ({"movie_title": " Moon  Garden "}, {"batch 1/r#1?x", "r2", "r3"}),
                ({"sentiment": "positive"}, {"batch 1/r#1?x", "r4"}),
                ({"movie_title": "Moon Garden", "sentiment": "negative"}, {"r3"}),
                ({"movie_title": "Unknown"}, set()),
            ):
                with self.subTest(filters=filters):
                    status, found = request(data_url + "/reviews?" + urlencode(filters))
                    self.assertEqual(status, 200)
                    self.assertEqual({row["external_id"] for row in found}, expected)
            self.assertEqual(call(url + "/counts?" + urlencode({"movie_title": " Moon  Garden "})),
                             (200, {"movie_title": "Moon Garden", "positive": 1,
                                    "neutral": 1, "negative": 1, "total": 3}))
            self.assertEqual(call(url + "/counts?movie_title=Unknown"),
                             (200, {"movie_title": "Unknown", "positive": 0,
                                    "neutral": 0, "negative": 0, "total": 0}))

    def test_reviews_pipeline_identical_reimports_preserve_all_records(self):
        rows = [("batch 1/r#1?x", " Moon   Garden ", "Wonderful acting"),
                ("r2", "Moon Garden", "Awful dialogue")]
        with self.running_review_pipeline() as (url, data_url):
            self.assertEqual(call(url + "/imports", self.review_csv(rows))[1]["added"], 2)
            before = self.review_snapshot()
            counts_before = call(url + "/counts?movie_title=Moon%20Garden")
            for incoming in (rows, [(identifier, "Moon Garden", text) for identifier, _, text in rows]):
                with self.subTest(rows=incoming):
                    status, result = call(url + "/imports", self.review_csv(incoming))
                    self.assertEqual(status, 200)
                    self.assertEqual((result["added"], result["duplicates"], result["skipped"]), (0, 2, 0))
                    self.assertEqual(FakeAI.calls, 2)
                    self.assertEqual(self.review_snapshot(), before)
                    self.assertEqual(call(url + "/counts?movie_title=Moon%20Garden"), counts_before)

    def test_reviews_pipeline_conflicting_ids_preserve_original(self):
        with self.running_review_pipeline() as (url, data_url):
            raw = self.review_csv([("r1", "Moon Garden", "Wonderful acting")])
            self.assertEqual(call(url + "/imports", raw)[1]["added"], 1)
            before = self.review_snapshot()
            for row in (("r1", "Other Movie", "Wonderful acting"),
                        ("r1", "Moon Garden", "Awful acting")):
                with self.subTest(row=row):
                    status, result = call(url + "/imports", self.review_csv([row]))
                    self.assertEqual(status, 200)
                    self.assertEqual((result["added"], result["duplicates"], result["skipped"]), (0, 0, 1))
                    self.assertEqual(result["rows"][0]["reason"], "review_id already used for a different review")
                    self.assertEqual(self.review_snapshot(), before)
                    self.assertEqual(FakeAI.calls, 1)

    def test_reviews_pipeline_counts_include_over_100_imported_reviews(self):
        with self.running_review_pipeline() as (url, data_url):
            texts = ("Wonderful acting", "A film about a town", "Awful dialogue")
            for start in range(0, 105, 20):
                rows = [(f"r{index}", "Moon Garden", texts[index % 3])
                        for index in range(start, min(start + 20, 105))]
                status, result = call(url + "/imports", self.review_csv(rows))
                self.assertEqual(status, 200)
                self.assertEqual((result["added"], result["duplicates"], result["skipped"]), (len(rows), 0, 0))
            self.assertEqual(self.review_counts(), (1, 105, 105))
            self.assertEqual(FakeAI.calls, 105)
            self.assertEqual(len(request(data_url + "/reviews?movie_title=Moon%20Garden")[1]), 100)
            self.assertEqual(call(url + "/counts?movie_title=Moon%20Garden"),
                             (200, {"movie_title": "Moon Garden", "positive": 35,
                                    "neutral": 35, "negative": 35, "total": 105}))

    def test_reviews_pipeline_csv_validation_and_20_row_boundary(self):
        with self.running_review_pipeline() as (url, data_url):
            rows = [(f"r{index}", "Moon Garden", "Wonderful acting") for index in range(20)]
            status, result = call(url + "/imports", self.review_csv(rows))
            self.assertEqual(status, 200)
            self.assertEqual((result["added"], result["duplicates"], result["skipped"]), (20, 0, 0))
            before = self.review_snapshot()
            for raw in (b"\xff\xfe", b"", b"review_id,movie_title\nr1,Moon Garden\n",
                        self.review_csv([]), self.review_csv(rows + [("r21", "Moon Garden", "Fine film")])):
                with self.subTest(raw_prefix=raw[:60]):
                    status, body = call(url + "/imports", raw)
                    self.assertEqual(status, 400)
                    self.assertIn("error", body)
                    self.assertEqual(self.review_snapshot(), before)
                    self.assertEqual(FakeAI.calls, 20)

    def test_reviews_pipeline_one_mib_upload_boundary(self):
        from http.client import HTTPConnection
        from urllib.parse import urlsplit
        from common import MAX_BODY_BYTES

        with self.running_review_pipeline() as (url, data_url):
            raw = self.review_csv([("r1", "Moon Garden", "Wonderful acting")])
            remaining = MAX_BODY_BYTES - len(raw)
            # Blank CSV lines pad the body without exceeding any field limits.
            block = b" " * 1023 + b"\n"
            raw += block * (remaining // len(block)) + b"\n" * (remaining % len(block))
            self.assertEqual(len(raw), 1024 * 1024)
            status, result = call(url + "/imports", raw)
            self.assertEqual(status, 200)
            self.assertEqual((result["added"], result["duplicates"], result["skipped"]), (1, 0, 0))
            before = self.review_snapshot()
            # Send the oversized header alone: rejection must precede body reading.
            connection = HTTPConnection(urlsplit(url).netloc, timeout=5)
            try:
                connection.putrequest("POST", "/imports")
                connection.putheader("Content-Type", "text/csv")
                connection.putheader("Content-Length", str(MAX_BODY_BYTES + 1))
                connection.endheaders()
                with connection.getresponse() as response:
                    self.assertEqual(response.status, 413)
                    self.assertIn(b"Request body must be at most", response.read())
            finally:
                connection.close()
            self.assertEqual(self.review_snapshot(), before)
            self.assertEqual(FakeAI.calls, 1)

    def test_reviews_pipeline_invalid_rows_do_not_block_valid_rows(self):
        rows = [("good", "Moon Garden", "Wonderful acting"),
                ("", "Moon Garden", "Fine film"), ("bad-movie", " ", "Fine film"),
                ("bad-text", "Moon Garden", " "), ("long", "Moon Garden", "x" * 1001)]
        with self.running_review_pipeline() as (url, data_url):
            status, result = call(url + "/imports", self.review_csv(rows))
            self.assertEqual(status, 200)
            self.assertEqual((result["added"], result["duplicates"], result["skipped"]), (1, 0, 4))
            self.assertTrue(all(entry.get("reason") for entry in result["rows"][1:]))
            self.assertEqual(self.review_counts(), (1, 1, 1))
            self.assertEqual(FakeAI.calls, 1)
            self.assertEqual([row["external_id"] for row in request(data_url + "/reviews")[1]], ["good"])

    def test_reviews_pipeline_ai_failure_does_not_save_predictions(self):
        with self.running_review_pipeline(ai_handler=Down) as (url, data_url):
            status, result = call(url + "/imports", self.review_csv([
                ("r1", "Moon Garden", "Wonderful acting"), ("r2", "Moon Garden", "Fine film"),
            ]))
            self.assertEqual(status, 200)
            self.assertEqual((result["added"], result["duplicates"], result["skipped"]), (0, 0, 2))
            self.assertEqual({entry["reason"] for entry in result["rows"]}, {"service unavailable"})
            self.assertEqual(self.review_counts(), (0, 0, 0))
            self.assertEqual(request(data_url + "/healthz"), (200, {"service": "data", "status": "ok"}))

    def test_reviews_pipeline_later_ai_failure_preserves_saved_rows(self):
        from common import APIError

        class FailAfterOneAI(FakeAI):
            def route(self, method, path):
                if FakeAI.calls >= 1:
                    raise APIError(503, "Synthetic AI failure")
                return super().route(method, path)

        with self.running_review_pipeline(ai_handler=FailAfterOneAI) as (url, data_url):
            rows = [(f"r{index}", "Moon Garden", "Wonderful acting") for index in range(3)]
            status, result = call(url + "/imports", self.review_csv(rows))
            self.assertEqual(status, 200)
            self.assertEqual((result["added"], result["duplicates"], result["skipped"]), (1, 0, 2))
            self.assertEqual([entry["status"] for entry in result["rows"]], ["added", "skipped", "skipped"])
            self.assertEqual({entry["reason"] for entry in result["rows"][1:]}, {"service unavailable"})
            self.assertEqual(self.review_counts(), (1, 1, 1))
            self.assertEqual([row["external_id"] for row in request(data_url + "/reviews")[1]], ["r0"])

    def test_reviews_pipeline_database_failure_propagates_through_real_data(self):
        with self.running_review_pipeline() as (url, data_url):
            # Inject failure only at the database boundary; both HTTP handlers stay real.
            with patch.object(data, "connect", side_effect=psycopg.OperationalError("synthetic private detail")):
                self.assertEqual(request(data_url + "/healthz"),
                                 (503, {"error": "Database unavailable. Please try again."}))
                status, result = call(url + "/imports", self.review_csv([
                    ("r1", "Moon Garden", "Wonderful acting"), ("r2", "Moon Garden", "Fine film"),
                ]))
                self.assertEqual(status, 200)
                self.assertEqual((result["added"], result["duplicates"], result["skipped"]), (0, 0, 2))
                self.assertEqual({entry["reason"] for entry in result["rows"]}, {"service unavailable"})
                self.assertEqual(call(url + "/counts?movie_title=Moon%20Garden"),
                                 (503, {"error": "A required service is unavailable. Please try again."}))
                self.assertEqual(FakeAI.calls, 0)
            self.assertEqual(self.review_counts(), (0, 0, 0))
            self.assertEqual(request(data_url + "/healthz")[0], 200)

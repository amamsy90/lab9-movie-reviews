"""Optional PostgreSQL integration tests; every test owns a temporary schema.

Run with TEST_DATABASE=1 and the data service's DB_* variables pointing at a
throwaway database. Compose CI runs these inside the data image.
"""
from concurrent.futures import ThreadPoolExecutor
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
from test_app import server
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

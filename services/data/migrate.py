"""Apply ordered SQL migrations atomically; safe to run at every startup."""
from hashlib import sha256
import json
from pathlib import Path
import re

from psycopg import sql

from project import CATEGORIES

MIGRATIONS = Path(__file__).with_name("migrations")


def migrate(connection, directory=MIGRATIONS):
    files = sorted(Path(directory).glob("*.sql"))
    versions = [path.name.split("_", 1)[0] for path in files]
    if (not files or len(set(versions)) != len(versions)
            or any(not re.fullmatch(r"[0-9]{3}_[a-z0-9_]+\.sql", p.name) for p in files)):
        raise ValueError("Use unique NNN_description.sql migration filenames.")
    with connection.transaction():
        # Serializes concurrent service startups; released on commit or rollback.
        connection.execute("SELECT pg_advisory_xact_lock(2026110901)")
        connection.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            checksum TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
        applied = {row["version"]: row["checksum"] for row in connection.execute(
            "SELECT version, checksum FROM schema_migrations"
        ).fetchall()}
        if set(applied) - {path.name for path in files}:
            raise ValueError("An applied migration is missing from the release.")
        for path in files:
            text = path.read_text()
            # Only the initial schema is a template; later SQL may contain braces.
            initial = path.name == "001_initial.sql"
            checksum = sha256((text + (json.dumps(CATEGORIES) if initial else "")).encode()).hexdigest()
            if path.name in applied:
                if applied[path.name] != checksum:
                    raise ValueError(f"Applied migration changed: {path.name}; add a new migration.")
                continue
            if applied and path.name < max(applied):
                raise ValueError(f"Migration added out of order: {path.name}")
            statement = sql.SQL(text).format(categories=sql.SQL(", ").join(
                sql.Literal(category) for category in CATEGORIES
            )) if initial else text
            connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                (path.name, checksum),
            )


if __name__ == "__main__":
    from services.data.app import connect

    with connect() as connection:
        migrate(connection)
    print("Database migrations applied.")

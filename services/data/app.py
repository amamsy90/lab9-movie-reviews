"""Only this service owns the database and its credentials."""
import os
import re

import psycopg
from psycopg.rows import dict_row

from common import APIError, Handler, serve, validate_text
from project import CATEGORIES
from services.data.migrate import migrate


def connect():
    return psycopg.connect(
        host=os.environ.get("DB_HOST", "db"),
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ.get("DB_NAME", "helpdesk"),
        user=os.environ.get("DB_USER", "helpdesk"),
        password=os.environ["DB_PASSWORD"],
        connect_timeout=3,
        options="-c statement_timeout=3000",
        row_factory=dict_row,
    )


def serialize(row):
    return {**row, "created_at": row["created_at"].isoformat()}


class Data(Handler):
    def route(self, method, path):
        detail = re.fullmatch(r"/tickets/([1-9][0-9]{0,17})", path)
        if (method, path) not in {
            ("GET", "/healthz"), ("GET", "/tickets"), ("POST", "/tickets")
        } and not (method == "GET" and detail):
            raise APIError(404, "Not found.")
        payload = None
        if method == "POST":
            payload = self.body()
            text = validate_text(payload)
            category = payload.get("category")
            version = payload.get("model_version")
            if category not in CATEGORIES:
                raise APIError(400, "Invalid category.")
            if not isinstance(version, str) or not 1 <= len(version) <= 100:
                raise APIError(400, "Invalid model version.")
        elif path == "/tickets":
            query = self.query_param("q").strip()
            category = self.query_param("category")
            if len(query) > 1000:
                raise APIError(400, "Search text must be at most 1000 characters.")
            if category and category not in CATEGORIES:
                raise APIError(400, "Invalid category.")
        try:
            with connect() as connection:
                if path == "/healthz":
                    connection.execute("SELECT 1")
                    result = {"service": "data", "status": "ok"}
                elif detail:
                    row = connection.execute(
                        "SELECT * FROM tickets WHERE id = %s", (int(detail[1]),)
                    ).fetchone()
                    if row is None:
                        raise APIError(404, "Unknown ticket ID.")
                    result = serialize(row)
                elif method == "GET":
                    rows = connection.execute(
                        "SELECT * FROM tickets WHERE (%s = '' OR strpos(lower(text), lower(%s)) > 0) "
                        "AND (%s = '' OR category = %s) ORDER BY id DESC LIMIT 100",
                        (query, query, category, category),
                    ).fetchall()
                    result = [serialize(row) for row in rows]
                else:
                    row = connection.execute(
                        "INSERT INTO tickets (text, category, model_version) "
                        "VALUES (%s, %s, %s) RETURNING *", (text, category, version)
                    ).fetchone()
                    result = serialize(row)
            # Send success only after the transaction has committed.
            return self.send(201 if payload is not None else 200, result)
        except psycopg.errors.UniqueViolation as error:
            raise APIError(409, "A record with this unique value already exists.") from error
        except psycopg.errors.ForeignKeyViolation as error:
            raise APIError(409, "The referenced record is missing or still in use.") from error
        except (psycopg.IntegrityError, psycopg.DataError) as error:
            raise APIError(400, "The data does not satisfy the database constraints.") from error
        except (psycopg.OperationalError, psycopg.InterfaceError) as error:
            raise APIError(503, "Database unavailable. Please try again.") from error
        except psycopg.Error as error:
            raise APIError(500, "A database operation failed.") from error


if __name__ == "__main__":
    with connect() as connection:
        migrate(connection)
    serve(Data)

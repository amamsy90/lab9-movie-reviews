
"""Only the data service connects directly to PostgreSQL."""

import os
import re

import psycopg
from psycopg.rows import dict_row

from common import APIError, Handler, serve, validate_text
from project import CATEGORIES
from services.data.migrate import migrate


# These are the only sentiment labels accepted by our database.
SENTIMENTS = {"positive", "neutral", "negative"}

# Define the maximum length of each review field.
REVIEW_LIMITS = {
    "external_id": 100,
    "movie_title": 200,
    "review_text": 1000,
    "model_version": 100,
}


def connect():
    # Open a database connection using environment variables.
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
    # Convert the database timestamp to a JSON-compatible string.
    return {**row, "created_at": row["created_at"].isoformat()}


def validate_review(payload):
    # A review must be sent as a JSON object.
    if not isinstance(payload, dict):
        raise APIError(400, "Review must be a JSON object.")

    cleaned = {}

    # Check that every required text field is present and valid.
    for field, maximum in REVIEW_LIMITS.items():
        value = payload.get(field)

        if not isinstance(value, str):
            raise APIError(400, f"Invalid {field}.")

        # Remove leading and trailing spaces.
        value = value.strip()

        # Movie titles also need repeated spaces collapsed.
        if field == "movie_title":
            value = " ".join(value.split())

        if not 1 <= len(value) <= maximum:
            raise APIError(
                400,
                f"{field} must contain between 1 and {maximum} characters.",
            )

        cleaned[field] = value

    # Only the three agreed sentiment labels are allowed.
    sentiment = payload.get("sentiment")
    if sentiment not in SENTIMENTS:
        raise APIError(400, "Invalid sentiment.")

    cleaned["sentiment"] = sentiment
    return cleaned


class Data(Handler):
    def route(self, method, path):
        # Identify the existing ticket-detail route.
        ticket_detail = re.fullmatch(
            r"/tickets/([1-9][0-9]{0,17})", path
        )

        # Identify a review by its original CSV review ID.
        review_detail = re.fullmatch(
            r"/reviews/by-external-id/([^/]+)", path
        )

        # Allow only the agreed API endpoints.
        allowed = {
            ("GET", "/healthz"),
            ("GET", "/tickets"),
            ("POST", "/tickets"),
            ("GET", "/reviews"),
            ("POST", "/reviews"),
            ("GET", "/movies"),
        }

        if (
            (method, path) not in allowed
            and not (method == "GET" and ticket_detail)
            and not (method == "GET" and review_detail)
        ):
            raise APIError(404, "Not found.")

        payload = None

        # Validate incoming data before connecting to PostgreSQL.
        if method == "POST":
            payload = self.body()

            if path == "/tickets":
                text = validate_text(payload)
                category = payload.get("category")
                version = payload.get("model_version")

                if category not in CATEGORIES:
                    raise APIError(400, "Invalid category.")

                if not isinstance(version, str) or not 1 <= len(version) <= 100:
                    raise APIError(400, "Invalid model version.")

            else:
                review = validate_review(payload)

        elif path == "/tickets":
            query = self.query_param("q").strip()
            category = self.query_param("category")

            if len(query) > 1000:
                raise APIError(
                    400,
                    "Search text must be at most 1000 characters.",
                )

            if category and category not in CATEGORIES:
                raise APIError(400, "Invalid category.")

        elif path == "/reviews":
            # Read the optional movie and sentiment filters.
            movie_title = self.query_param("movie_title")
            sentiment = self.query_param("sentiment")
            all_reviews = self.query_param("all")

            # Normalize movie titles in the same way as imports.
            movie_title = " ".join(movie_title.split())

            if len(movie_title) > 200:
                raise APIError(400, "Movie title is too long.")

            if sentiment and sentiment not in SENTIMENTS:
                raise APIError(400, "Invalid sentiment.")

            if all_reviews not in ("", "true", "false"):
                raise APIError(400, "Invalid all parameter.")

            # The unlimited option is only for one movie.
            if all_reviews == "true" and not movie_title:
                raise APIError(
                    400,
                    "movie_title is required when all=true.",
                )

        try:
            # A database connection is opened for each request.
            with connect() as connection:

                if path == "/healthz":
                    # Check that PostgreSQL is responding.
                    connection.execute("SELECT 1")
                    result = {"service": "data", "status": "ok"}

                elif ticket_detail:
                    # Preserve the original ticket lookup.
                    row = connection.execute(
                        "SELECT * FROM tickets WHERE id = %s",
                        (int(ticket_detail[1]),),
                    ).fetchone()

                    if row is None:
                        raise APIError(404, "Unknown ticket ID.")

                    result = serialize(row)

                elif review_detail:
                    # Find a review using its external CSV ID.
                    from urllib.parse import unquote

                    external_id = unquote(review_detail[1])

                    row = connection.execute(
                        "SELECT * FROM reviews WHERE external_id = %s",
                        (external_id,),
                    ).fetchone()

                    if row is None:
                        raise APIError(404, "Review not found.")

                    result = serialize(row)

                elif path == "/movies":
                    # Return all distinct movie titles alphabetically.
                    rows = connection.execute(
                        "SELECT DISTINCT movie_title FROM reviews "
                        "ORDER BY movie_title"
                    ).fetchall()

                    result = [row["movie_title"] for row in rows]

                elif path == "/reviews" and method == "GET":
                    # Build a safe SQL query with optional filters.
                    sql = (
                        "SELECT * FROM reviews "
                        "WHERE (%s = '' OR movie_title = %s) "
                        "AND (%s = '' OR sentiment = %s) "
                        "ORDER BY id DESC"
                    )

                    parameters = [
                        movie_title,
                        movie_title,
                        sentiment,
                        sentiment,
                    ]

                    # Normally return at most 100 reviews.
                    if all_reviews != "true":
                        sql += " LIMIT 100"

                    rows = connection.execute(
                        sql, parameters
                    ).fetchall()

                    result = [serialize(row) for row in rows]

                elif path == "/reviews" and method == "POST":
                    # Save a new review and return the stored record.
                    row = connection.execute(
                        "INSERT INTO reviews "
                        "(external_id, movie_title, review_text, "
                        "sentiment, model_version) "
                        "VALUES (%s, %s, %s, %s, %s) "
                        "RETURNING *",
                        (
                            review["external_id"],
                            review["movie_title"],
                            review["review_text"],
                            review["sentiment"],
                            review["model_version"],
                        ),
                    ).fetchone()

                    result = serialize(row)

                elif path == "/tickets" and method == "GET":
                    # Preserve the original ticket list and filters.
                    rows = connection.execute(
                        "SELECT * FROM tickets "
                        "WHERE (%s = '' OR strpos(lower(text), lower(%s)) > 0) "
                        "AND (%s = '' OR category = %s) "
                        "ORDER BY id DESC LIMIT 100",
                        (query, query, category, category),
                    ).fetchall()

                    result = [serialize(row) for row in rows]

                else:
                    # Preserve the original ticket creation endpoint.
                    row = connection.execute(
                        "INSERT INTO tickets "
                        "(text, category, model_version) "
                        "VALUES (%s, %s, %s) RETURNING *",
                        (text, category, version),
                    ).fetchone()

                    result = serialize(row)

            # Send success only after PostgreSQL commits.
            return self.send(
                201 if payload is not None else 200,
                result,
            )

        except psycopg.errors.UniqueViolation as error:
            # Duplicate review IDs must return the agreed error.
            if path == "/reviews":
                raise APIError(
                    409, "Review ID already exists."
                ) from error

            raise APIError(
                409,
                "A record with this unique value already exists.",
            ) from error

        except psycopg.errors.ForeignKeyViolation as error:
            raise APIError(
                409,
                "The referenced record is missing or still in use.",
            ) from error

        except (psycopg.IntegrityError, psycopg.DataError) as error:
            raise APIError(
                400,
                "The data does not satisfy the database constraints.",
            ) from error

        except (psycopg.OperationalError, psycopg.InterfaceError) as error:
            raise APIError(
                503,
                "Database unavailable. Please try again.",
            ) from error

        except psycopg.Error as error:
            raise APIError(
                500,
                "A database operation failed.",
            ) from error


if __name__ == "__main__":
    # Apply any pending database migrations before starting HTTP.
    with connect() as connection:
        migrate(connection)

    # Start the data microservice.
    serve(Data)

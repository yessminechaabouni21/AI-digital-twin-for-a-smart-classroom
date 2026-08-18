"""Verify the SQLAlchemy -> psycopg -> PostgreSQL connection.

Temporary diagnostic script. Reads the version() and current database name
only — does not create tables or write data.
"""

from __future__ import annotations

from sqlalchemy import text

from digital_twin.data.db.session import get_engine


def main() -> None:
    try:
        engine = get_engine()
        with engine.connect() as connection:
            version = connection.execute(text("SELECT version();")).scalar_one()
            db_name = connection.execute(text("SELECT current_database();")).scalar_one()

        print("Connection successful!")
        print(f"PostgreSQL version: {version}")
        print(f"Current database: {db_name}")
    except Exception as exc:
        print(f"Connection failed: {exc}")


if __name__ == "__main__":
    main()

"""Create the OULAD schema in PostgreSQL.

Temporary setup script. Uses Base.metadata.create_all, which is idempotent
(checkfirst=True by default) — existing tables are left untouched. Does not
insert any data.
"""

from __future__ import annotations

from digital_twin.data.db.models import Base
from digital_twin.data.db.session import get_engine


def main() -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)

    for table in Base.metadata.sorted_tables:
        print(f"Created table: {table.name}")

    print("All OULAD tables created successfully.")


if __name__ == "__main__":
    main()

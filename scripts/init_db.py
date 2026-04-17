"""Initialize the SQLite database from schema.sql."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.storage.db import get_default_db, apply_schema

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "../src/storage/schema.sql")

if __name__ == "__main__":
    conn = get_default_db()
    apply_schema(conn, SCHEMA_PATH)
    conn.close()
    print("Database initialized successfully.")

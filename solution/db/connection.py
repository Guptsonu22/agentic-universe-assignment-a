"""SQLite connection manager with WAL mode and strict relational integrity."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional, Union

from solution.config import Config


class DatabaseManager:
    """Manages SQLite connections, pragmas, and transactional contexts."""

    def __init__(self, db_path: Union[str, Path] = "au_ledger.db") -> None:
        self.db_path = str(db_path)

    def create_connection(self) -> sqlite3.Connection:
        """Create and configure a new sqlite3 connection with strict pragmas."""
        # Ensure parent directories exist for file-based databases
        if self.db_path != ":memory:" and not self.db_path.startswith("file:"):
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(
            self.db_path,
            timeout=10.0,
        )
        conn.row_factory = sqlite3.Row

        # Apply production-grade SQLite pragmas
        with conn:
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA busy_timeout = 5000;")
            if self.db_path != ":memory:":
                # Write-Ahead Logging for high concurrency and performance
                conn.execute("PRAGMA journal_mode = WAL;")
                conn.execute("PRAGMA synchronous = NORMAL;")

        return conn

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager yielding a managed connection."""
        conn = self.create_connection()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager that commits on clean exit or rolls back on exceptions."""
        conn = self.create_connection()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


@contextmanager
def get_connection(
    db_path: Optional[Union[str, Path]] = None,
) -> Generator[sqlite3.Connection, None, None]:
    """Convenience context manager resolving DB path from config if not provided."""
    if db_path is None:
        cfg = Config.load()
        db_path = cfg.database_path

    mgr = DatabaseManager(db_path)
    with mgr.connection() as conn:
        yield conn

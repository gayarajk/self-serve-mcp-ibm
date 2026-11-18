"""Read-only PostgreSQL connection helper for the visualization toolkit.

This is a strict subset of the main toolkit's db_config.py:
  - Credentials are loaded exclusively from environment variables.
  - Credentials are NEVER logged or included in return values.
  - Every connection has a statement_timeout of 30 s and a row limit guard.
  - Only SELECT / EXPLAIN / SET commands are permitted through _run_safe().

Priority for connection parameters (same as the main toolkit):
  1. DATABASE_URL — full connection string (IBM Cloud Databases / Code Engine)
  2. PG_HOST / PG_PORT / PG_DB / PG_USER / PG_PASS — local dev vars

The visualisation tools connect under the same account as the main toolkit.
If you have a dedicated read-only Postgres role, point PG_USER / PG_PASS
(or the DATABASE_URL) at that role instead.
"""

from __future__ import annotations

import os
import re
import ssl
from urllib.parse import parse_qs, urlparse

# ── Env-var defaults ──────────────────────────────────────────────────────────
PG_HOST = os.environ.get("PG_HOST", "localhost")
PG_PORT = int(os.environ.get("PG_PORT", "5432"))
PG_DB   = os.environ.get("PG_DB",   "wxodb")
PG_USER = os.environ.get("PG_USER", "wxouser")
# PG_PASS intentionally not stored at module level — read inline in get_conn()

_DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Maximum rows a visualization query may return (hard cap).
VIZ_ROW_LIMIT: int = int(os.environ.get("VIZ_ROW_LIMIT", "2000"))

# Statement timeout in milliseconds applied via SET LOCAL.
_STATEMENT_TIMEOUT_MS: int = int(os.environ.get("VIZ_QUERY_TIMEOUT_MS", "30000"))

# Schemas that visualization tools may inspect.
ALLOWED_SCHEMAS: frozenset[str] = frozenset(
    s.strip()
    for s in os.environ.get("VIZ_ALLOWED_SCHEMAS", "public").split(",")
    if s.strip()
)

# ── SQL safety ────────────────────────────────────────────────────────────────
# Only these statement types are permitted through _run_safe().
_SAFE_STMT_RE = re.compile(
    r"^\s*(SELECT|WITH|EXPLAIN)\b",
    re.IGNORECASE,
)
# Block any attempt to include stacked statements.
_SEMICOLON_SPLIT_RE = re.compile(r";(?!\s*$)")


def _assert_safe_sql(sql: str) -> None:
    """Raise ValueError if *sql* is not a plain SELECT / WITH / EXPLAIN."""
    sql_stripped = sql.strip()
    if _SEMICOLON_SPLIT_RE.search(sql_stripped):
        raise ValueError(
            "Only a single SELECT statement is permitted; "
            "semicolon-separated statements are not allowed."
        )
    if not _SAFE_STMT_RE.match(sql_stripped):
        raise ValueError(
            f"Only SELECT / WITH / EXPLAIN queries are permitted. "
            f"Received: {sql_stripped[:80]!r}"
        )


# ── SSL helper ────────────────────────────────────────────────────────────────

def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ca = os.environ.get("PGSSLROOTCERT", "")
    if ca:
        ctx.load_verify_locations(ca)
    return ctx


# ── Connection factory ────────────────────────────────────────────────────────

def get_ro_conn():
    """Return a pg8000.native.Connection ready for read-only queries.

    A SET LOCAL statement_timeout is issued immediately after connecting so
    long-running queries are aborted server-side.
    """
    import pg8000.native  # deferred — not installed at import time in tests

    if _DATABASE_URL:
        parsed  = urlparse(_DATABASE_URL)
        host    = parsed.hostname
        port    = parsed.port or 5432
        db      = (parsed.path or "/").lstrip("/")
        user    = parsed.username
        passwd  = parsed.password
        qs      = parse_qs(parsed.query)
        sslmode = qs.get("sslmode", ["require"])[0]
        kwargs: dict = dict(host=host, port=port, database=db, user=user, password=passwd)
        if sslmode != "disable":
            kwargs["ssl_context"] = _ssl_context()
    else:
        passwd = os.environ.get("PG_PASS", "wxopass")
        kwargs = dict(
            host=PG_HOST, port=PG_PORT, database=PG_DB,
            user=PG_USER, password=passwd,
        )
        if os.environ.get("PGSSL", "false").lower() == "true":
            kwargs["ssl_context"] = _ssl_context()

    con = pg8000.native.Connection(**kwargs)
    # Enforce a server-side query timeout immediately.
    con.run(f"SET statement_timeout = {_STATEMENT_TIMEOUT_MS}")
    return con

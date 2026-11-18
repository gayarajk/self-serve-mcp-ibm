"""Shared PostgreSQL connection helper.

Priority order for connection parameters:
  1. DATABASE_URL  — full connection string (used by IBM Cloud Databases for PostgreSQL
                     and Code Engine secrets).  SSL is enabled automatically when the
                     URL contains 'sslmode' or when PGSSL=true is set.
  2. PG_HOST / PG_PORT / PG_DB / PG_USER / PG_PASS individual env vars
                   — used for local development.

Usage in every tool:
    from db_config import get_conn, PG_DB, PG_HOST
    con = get_conn()
"""

import os
import ssl
from urllib.parse import urlparse, parse_qs

# ── Individual env-var fallbacks (local dev) ──────────────────────────────────
PG_HOST = os.environ.get("PG_HOST", "localhost")
PG_PORT = int(os.environ.get("PG_PORT", "5432"))
PG_DB   = os.environ.get("PG_DB",   "wxodb")
PG_USER = os.environ.get("PG_USER", "wxouser")
PG_PASS = os.environ.get("PG_PASS", "wxopass")

# ── Full connection string (IBM Cloud Databases / Code Engine secret) ─────────
_DATABASE_URL = os.environ.get("DATABASE_URL", "")


def _ssl_context() -> ssl.SSLContext:
    """Return a default SSL context that verifies the server certificate."""
    ctx = ssl.create_default_context()
    # IBM Cloud Databases supplies its own CA; if a cert file is provided use it.
    _ca = os.environ.get("PGSSLROOTCERT", "")
    if _ca:
        ctx.load_verify_locations(_ca)
    return ctx


def get_conn():
    """Return a pg8000.native.Connection, with SSL when DATABASE_URL is set.

    When DATABASE_URL is present (IBM Cloud Databases / Code Engine) SSL is
    always used unless the URL explicitly contains ``sslmode=disable``.
    When only PG_* vars are present (local dev) SSL is skipped by default
    unless ``PGSSL=true`` is set.
    """
    import pg8000.native

    if _DATABASE_URL:
        # ── Parse the URL ─────────────────────────────────────────────────────
        parsed = urlparse(_DATABASE_URL)
        host   = parsed.hostname
        port   = parsed.port or 5432
        db     = (parsed.path or "/").lstrip("/")
        user   = parsed.username
        passwd = parsed.password

        qs = parse_qs(parsed.query)
        sslmode = qs.get("sslmode", ["require"])[0]

        if sslmode == "disable":
            return pg8000.native.Connection(
                host=host, port=port, database=db, user=user, password=passwd,
            )
        else:
            return pg8000.native.Connection(
                host=host, port=port, database=db, user=user, password=passwd,
                ssl_context=_ssl_context(),
            )

    else:
        # ── Individual env vars (local dev) ───────────────────────────────────
        use_ssl = os.environ.get("PGSSL", "false").lower() == "true"
        kwargs = dict(
            host=PG_HOST, port=PG_PORT, database=PG_DB,
            user=PG_USER, password=PG_PASS,
        )
        if use_ssl:
            kwargs["ssl_context"] = _ssl_context()
        return pg8000.native.Connection(**kwargs)

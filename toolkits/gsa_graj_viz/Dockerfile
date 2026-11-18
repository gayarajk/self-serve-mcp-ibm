FROM python:3.12-slim

WORKDIR /app

# Apply all available OS security patches before installing application deps.
# This remediation layer addresses the same CVEs as gsa_graj_tools:
#   CVE-2026-85091 — zlib heap buffer overflow via stale gzwrite pointer
#                    (zlib 1.2.11–1.3.2; fixed in Debian deb13u1)
#   CVE-2026-27171 — zlib infinite-loop DoS in crc32_combine_gen64
#                    (zlib < 1.3.2; fixed in Debian deb13u1)
#   CVE-2025-8869  — pip tar symlink escape (< 25.3)
#   CVE-2026-1703  — pip wheel path traversal (< 26.0)
#   CVE-2026-3219  — pip zip/tar ambiguity (< 26.1)
#   CVE-2026-6357  — pip self-update import hijack (< 26.1)
#   CVE-2026-8643  — pip console_scripts path traversal (< 26.1.2)
#   CVE-2026-13346 — pip doubly-encoded URL traversal (< 26.2)
# renovate: datasource=repology depName=debian_13/zlib versioning=deb
RUN apt-get update -qq \
 && apt-get upgrade -y --no-install-recommends \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir "pip>=26.3"

# Install dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy toolkit source
COPY server.py db_config.py ./

# FastMCP selects transport by PORT env var (see server.py):
#   PORT set  → HTTP (streamable-http) on that port
#   PORT unset → stdio (local dev / testing)
# We expose 8000 and default PORT=8000 for Code Engine / container deployments.
EXPOSE 8000

ENV PORT=8000

# Environment variables expected at runtime (inject via Code Engine secrets):
#   DATABASE_URL — full Neon / ICD connection string  (or PG_HOST/PORT/DB/USER/PASS)
#   PGSSLROOTCERT — optional path to CA cert for sslmode=verify-full
#   VIZ_ROW_LIMIT — maximum rows returned per query (default 2000)
#   VIZ_QUERY_TIMEOUT_MS — server-side statement timeout ms (default 30000)
#   VIZ_ALLOWED_SCHEMAS — comma-separated list of schemas (default: public)

CMD ["python", "server.py"]

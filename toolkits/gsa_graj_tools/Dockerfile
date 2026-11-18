FROM python:3.12-slim

WORKDIR /app

# Apply all available OS security patches before installing application deps.
# This remediation layer addresses:
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

# Install application dependencies (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy toolkit source
COPY server.py db_config.py ./

# FastMCP server selects transport by PORT env var (see server.py):
#   PORT set  → HTTP (streamable-http) on that port
#   PORT unset → stdio (local dev / testing)
# We expose 8000 and default PORT=8000 for Code Engine / container deployments.
EXPOSE 8000

ENV PORT=8000

CMD ["python", "server.py"]

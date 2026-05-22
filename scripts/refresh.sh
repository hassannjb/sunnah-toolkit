#!/usr/bin/env bash
# Monthly dataset refresh for sunnah-toolkit.
#
# Sunnah.com asks downstream apps to refresh the data at least once a month
# so upstream corrections (text fixes, grading updates, new translations)
# propagate. They publish a fresh dump by overwriting the file at the same
# static URL (https://sunnah.com/HadithTable.sql.gz) when corrections land.
#
# This wrapper:
#
#   1. HTTP conditional-GET the dump (curl -z compares local mtime to the
#      server's Last-Modified). If unchanged, exit 0 with a "no work to
#      do" message. If newer, download in place.
#   2. Rebuild data/hadith.sqlite from the new dump.
#   3. Rebuild data/embeddings.npy against the new SQLite corpus.
#   4. Rebuild the Docker image (sunnah-toolkit:latest), tagging the old
#      image as sunnah-toolkit:previous for easy rollback.
#   5. Stop + restart the running `sunnah` container against the new image.
#   6. Smoke-test /healthz on localhost:8000.
#
# No API key needed — the dump endpoint is a public download. The API key
# is only for api.sunnah.com (5 req/s, 5,000 req/day); never bundle it.
#
# Flags:
#   --no-image    Skip steps 4–5. Refresh only the local SQLite + embeddings
#                 (for stdio-MCP users who don't run the container).
#   --no-deploy   Skip step 5. Rebuild the image but leave the running
#                 container alone.
#   --help        Show this message.
#
# Rollback:
#   docker tag sunnah-toolkit:previous sunnah-toolkit:latest
#   docker stop sunnah && docker rm sunnah
#   docker run -d --restart unless-stopped -p 8000:8000 \
#     --name sunnah sunnah-toolkit:latest

set -euo pipefail

NO_IMAGE=0
NO_DEPLOY=0
for arg in "$@"; do
    case "$arg" in
        --no-image)  NO_IMAGE=1 ;;
        --no-deploy) NO_DEPLOY=1 ;;
        --help|-h)
            # Strip the leading shebang, then print the leading comment block
            # (lines starting with '#'). awk stops at the first non-comment
            # line so this stays in sync with the docstring above.
            awk 'NR == 1 { next }
                 /^#/ { sub(/^# ?/, ""); print; next }
                 { exit }' "$0"
            exit 0 ;;
        *)
            echo "error: unknown flag '$arg' (try --help)" >&2
            exit 64 ;;
    esac
done

# Run from the repo root regardless of where the script was invoked.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

DUMP="data/HadithTable.sql.gz"
DUMP_URL="https://sunnah.com/HadithTable.sql.gz"

PYTHON=".venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
    PYTHON="python3"
fi

echo "==> [1/4] check $DUMP_URL"
mkdir -p "$(dirname "$DUMP")"

# Capture mtime before; if curl -z gets a 304 it leaves the file untouched.
prev_mtime=$(stat -f "%m" "$DUMP" 2>/dev/null || echo 0)

# -R preserves the server's Last-Modified time on the downloaded file
# so future -z comparisons stay accurate. -z makes this a conditional GET.
# -f returns nonzero on HTTP errors. -L follows redirects.
http_status=$(curl -fsSL -R \
    ${prev_mtime:+-z "$DUMP"} \
    -o "$DUMP" \
    -w "%{http_code}" \
    "$DUMP_URL")

new_mtime=$(stat -f "%m" "$DUMP" 2>/dev/null || echo 0)
if [[ "$prev_mtime" -ne 0 && "$new_mtime" -le "$prev_mtime" ]]; then
    echo "Dump is up to date (last modified $(date -r "$DUMP" "+%Y-%m-%d %H:%M:%S"))."
    echo "Nothing to rebuild — exiting."
    exit 0
fi

if [[ "$prev_mtime" -eq 0 ]]; then
    echo "First-time download (HTTP $http_status). Size: $(ls -lh "$DUMP" | awk '{print $5}')"
else
    echo "New dump downloaded (server-time $(date -r "$DUMP" "+%Y-%m-%d %H:%M:%S"))."
fi

echo
echo "==> [2/4] build_sqlite"
"$PYTHON" -m scripts.build_sqlite
echo
echo "==> [3/4] build_embeddings"
"$PYTHON" -m scripts.build_embeddings

if [[ $NO_IMAGE -eq 1 ]]; then
    echo
    echo "==> [4/4] skipped (--no-image)"
    echo "Local stdio MCP is now refreshed. Container untouched."
    exit 0
fi

echo
echo "==> [4/4] docker build"
# Save rollback tag pointing at the current :latest if one exists.
if docker image inspect sunnah-toolkit:latest >/dev/null 2>&1; then
    docker tag sunnah-toolkit:latest sunnah-toolkit:previous
    echo "    tagged previous image as sunnah-toolkit:previous (for rollback)"
fi
docker build -t sunnah-toolkit:latest .

if [[ $NO_DEPLOY -eq 1 ]]; then
    echo
    echo "Image rebuilt. Container restart skipped (--no-deploy)."
    exit 0
fi

echo
echo "==> Restarting container"
if docker ps -a --format '{{.Names}}' | grep -q '^sunnah$'; then
    docker stop sunnah >/dev/null && docker rm sunnah >/dev/null
fi
docker run -d --restart unless-stopped -p 8000:8000 \
    --name sunnah sunnah-toolkit:latest >/dev/null

echo
echo "==> Waiting for /healthz"
for i in {1..30}; do
    if curl -sf http://localhost:8000/healthz > /dev/null 2>&1; then
        echo "READY after ${i}x2s"
        break
    fi
    sleep 2
done

if curl -sf http://localhost:8000/healthz > /dev/null 2>&1; then
    echo
    echo "Refresh complete. Container is healthy at http://localhost:8000."
    echo "Rollback if needed:"
    echo "  docker tag sunnah-toolkit:previous sunnah-toolkit:latest"
    echo "  docker stop sunnah && docker rm sunnah"
    echo "  docker run -d --restart unless-stopped -p 8000:8000 \\"
    echo "    --name sunnah sunnah-toolkit:latest"
else
    echo "warning: /healthz never came up. Check 'docker logs sunnah'." >&2
    exit 1
fi

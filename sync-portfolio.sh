#!/usr/bin/env bash
# Manually sync the built MPI pages into the local Portfolio repo and push.
# Mirrors .github/workflows/sync-portfolio.yml for local use (no CI needed).
# Assumes the Portfolio repo is checked out as a sibling directory: ../Portfolio
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
SRC="$ROOT/output"
DEST="$ROOT/../Portfolio/mpi"

if [ ! -f "$SRC/index.html" ]; then
  echo "ERROR: $SRC/index.html not found. Run 'python src/run_pipeline.py' first." >&2
  exit 1
fi

echo "Syncing output -> Portfolio/mpi ..."
rm -rf "$DEST"
mkdir -p "$DEST"
cp "$SRC/index.html" "$DEST/index.html"
cp "$SRC/billboard.html" "$DEST/billboard.html"

cd "$DEST/.."
git add mpi/
git commit -m "chore: sync MPI from Music-Popularity-Index" || echo "Nothing to commit."
git push
echo "Done."

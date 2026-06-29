"""
One-command pipeline runner. Runs the downstream steps in order so you don't
have to invoke them by hand after tweaking scoring.

    python src/run_pipeline.py          # full: score -> links -> csv -> html
    python src/run_pipeline.py --quick  # fast: score -> csv only (no html)

--quick skips the link resolution and HTML exports, which is what you usually
want while iterating on score.py.

The Spotify link step reads from the local top_10000_1950-now.csv — no API
calls, no rate limits, runs instantly.
"""

import os
import subprocess
import sys

BASE = os.path.dirname(__file__)


def run(script, extra_args=None):
    print(f"\n=== {script} ===")
    cmd = [sys.executable, os.path.join(BASE, script)] + (extra_args or [])
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"\nABORTED: {script} exited with code {result.returncode}")
        sys.exit(result.returncode)


def main():
    quick = "--quick" in sys.argv

    run("score.py")
    if not quick:
        run("fetch_spotify_links.py")
    run("export_csv.py")
    if not quick:
        run("export.py")
        run("export_billboard.py")
        run("export_streaming.py")

    print(f"\nPipeline complete.{' (quick mode)' if quick else ''}")


if __name__ == "__main__":
    main()

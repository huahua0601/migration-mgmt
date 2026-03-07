#!/usr/bin/env python3
"""Entrypoint: run Alembic migrations then start uvicorn."""
import os
import subprocess
import sys


def main():
    print("[entrypoint] Running database migrations ...")
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd="/app",
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"[entrypoint] Migration failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    print("[entrypoint] Migrations complete. Starting server ...")
    subprocess.run(
        ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"],
    )


if __name__ == "__main__":
    main()

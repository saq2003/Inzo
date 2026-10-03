"""Offline smoke test: builds the app and exercises /health without a server."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app.main import create_app


def main() -> int:
    app = create_app()
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200, resp.text
    print("smoke ok:", resp.json())
    return 0


if __name__ == "__main__":
    sys.exit(main())

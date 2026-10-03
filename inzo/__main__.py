"""Entry point for ``python -m inzo`` (and the ``inzo`` console script)."""

from __future__ import annotations


def main() -> None:
    """Launch the INZO API server."""
    from app.main import main as app_main

    app_main()


if __name__ == "__main__":
    main()

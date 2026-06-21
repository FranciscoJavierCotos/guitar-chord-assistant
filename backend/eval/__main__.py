"""Enables ``python -m eval`` to run the harness."""

from eval.runner import main

if __name__ == "__main__":
    raise SystemExit(main())

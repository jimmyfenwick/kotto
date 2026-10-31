"""Support python -m kotto without import-time execution."""

from kotto.cli.main import main

if __name__ == "__main__":
    raise SystemExit(main())

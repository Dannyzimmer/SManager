"""Allow ``python -m smanager.daemon`` to start the daemon."""

from .server import main

if __name__ == "__main__":
    raise SystemExit(main())

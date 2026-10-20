"""Entry point for ``python -m appdrop``."""

import sys


def main() -> int:
    """Launch the AppDrop application."""
    from appdrop.config import setup_logging

    setup_logging()

    # GUI launch will be implemented in Milestone 2.
    print("AppDrop is not yet ready to launch. Run pytest to verify the setup.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

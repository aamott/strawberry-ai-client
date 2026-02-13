"""Entry point for Strawberry AI Spoke.

Delegates to the CLI main function.
"""

import sys

from .ui.cli.__main__ import main as cli_main


def main() -> int:
    """Main entry point - runs CLI interface."""
    cli_main()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Entry point for Strawberry AI Spoke.

Delegates to the CLI UI main function.
"""

import sys

from .ui.cli import main as cli_main


def main() -> int:
    """Main entry point - runs CLI interface."""
    return cli_main()


if __name__ == "__main__":
    sys.exit(main())

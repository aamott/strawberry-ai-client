"""Entry point for Strawberry AI Spoke."""

import argparse
import sys
from pathlib import Path

from .terminal import TerminalApp


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Strawberry AI Spoke - Voice Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "config" / "config.yaml",
        help="Path to config file (default: config/config.yaml)",
    )
    parser.add_argument(
        "--voice",
        action="store_true",
        help="Enable voice mode (requires API keys)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output",
    )

    args = parser.parse_args()

    app = TerminalApp(
        config_path=args.config,
        voice_mode=args.voice,
        debug=args.debug,
    )

    return app.run()


if __name__ == "__main__":
    sys.exit(main())

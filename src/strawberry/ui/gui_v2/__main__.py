"""Entry point for running GUI V2 as a package: python -m strawberry.ui.gui_v2"""

import logging
import sys

from .app import run_app_integrated

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

sys.exit(run_app_integrated())

"""Entrypoint for running skill_tester as a module.

Usage:
    python -m strawberry.testing.skill_tester_main
    python -m strawberry.testing.skill_tester_main --skills-dir /path/to/skills
"""

from .skill_tester import main

if __name__ == "__main__":
    main()

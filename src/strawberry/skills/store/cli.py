"""CLI interface for the skill store.

Provides subcommands: search, list, install, uninstall, update, installed.
Invoked via ``strawberry-cli store <command> [args]``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from strawberry.skills.store.catalog import SkillCatalog
from strawberry.skills.store.installer import SkillInstaller
from strawberry.skills.store.models import CatalogEntry, InstalledSkill


def _resolve_paths(
    config_dir: Optional[Path] = None,
) -> tuple[Path, Path, Path]:
    """Resolve skills dir, config dir, and venv python path.

    Args:
        config_dir: Optional override for config directory.

    Returns:
        (skills_dir, config_dir, venv_python)
    """
    # Project root is 5 levels up from this file
    project_root = Path(__file__).parent.parent.parent.parent.parent

    # Store-managed installs live in a gitignored subtree so they do not
    # appear as commit changes in the tracked built-in skills directory.
    skills_dir = project_root / "skills" / ".installed"
    if config_dir is None:
        config_dir = project_root / "config"

    # Find the venv python
    venv_dir = project_root / ".venv"
    if venv_dir.exists():
        # Linux/macOS
        venv_python = venv_dir / "bin" / "python"
        if not venv_python.exists():
            # Windows
            venv_python = venv_dir / "Scripts" / "python.exe"
    else:
        venv_python = Path(sys.executable)

    return skills_dir, config_dir, venv_python


def _make_installer(
    config_dir: Optional[Path] = None,
) -> tuple[SkillInstaller, SkillCatalog]:
    """Create an installer and catalog with default paths.

    Args:
        config_dir: Optional override for config directory.

    Returns:
        (installer, catalog) tuple.
    """
    skills_dir, cfg_dir, venv_python = _resolve_paths(config_dir)
    catalog = SkillCatalog()
    installer = SkillInstaller(
        skills_dir=skills_dir,
        config_dir=cfg_dir,
        catalog=catalog,
        venv_python=venv_python,
    )
    return installer, catalog


# ── Formatting helpers ──────────────────────────────────────────────


def _format_catalog_entry(entry: CatalogEntry, installed_names: set) -> str:
    """Format a single catalog entry for display.

    Args:
        entry: The catalog entry.
        installed_names: Set of already-installed skill names.

    Returns:
        Formatted string.
    """
    status = " [installed]" if entry.name in installed_names else ""
    tags = ", ".join(entry.tags) if entry.tags else ""
    lines = [f"  {entry.name}{status}"]
    if entry.description:
        lines.append(f"    {entry.description}")
    if entry.author:
        lines.append(f"    Author: {entry.author}")
    if tags:
        lines.append(f"    Tags: {tags}")
    if entry.requires:
        lines.append(f"    Requires: {', '.join(entry.requires)}")
    return "\n".join(lines)


def _format_installed(record: InstalledSkill) -> str:
    """Format an installed skill record for display.

    Args:
        record: The install record.

    Returns:
        Formatted string.
    """
    source = "catalog" if record.from_catalog else record.source_url
    lines = [f"  {record.name}"]
    lines.append(f"    Source: {source}")
    if record.commit:
        lines.append(f"    Commit: {record.commit[:12]}")
    if record.installed_at:
        lines.append(f"    Installed: {record.installed_at[:19]}")
    if record.deps_installed:
        lines.append(
            f"    Dependencies: {', '.join(record.deps_installed)}"
        )
    return "\n".join(lines)


# ── Subcommand handlers ────────────────────────────────────────────


def cmd_list(args: argparse.Namespace) -> int:
    """List all skills in the catalog."""
    installer, catalog = _make_installer(args.config)

    entries = catalog.list_all()
    if not entries:
        print("Catalog is empty.")
        return 0

    # Get installed names for status display
    installed_names = {r.name for r in installer.list_installed()}

    print(f"Available skills ({len(entries)}):\n")
    for entry in entries:
        print(_format_catalog_entry(entry, installed_names))
        print()
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    """Search the catalog by keyword."""
    installer, catalog = _make_installer(args.config)
    query = " ".join(args.query)

    if not query.strip():
        print("Usage: strawberry-cli store search <query>")
        return 1

    results = catalog.search(query)
    if not results:
        print(f"No skills found matching '{query}'.")
        return 0

    installed_names = {r.name for r in installer.list_installed()}

    print(f"Found {len(results)} skill(s) matching '{query}':\n")
    for entry in results:
        print(_format_catalog_entry(entry, installed_names))
        print()
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    """Install a skill from catalog or URL."""
    installer, _catalog = _make_installer(args.config)
    name_or_url = args.name_or_url

    try:
        # Check if already installed
        if not args.force:
            record = installer.get_record(name_or_url)
            if record:
                print(
                    f"Skill '{name_or_url}' is already installed. "
                    f"Use --force to reinstall."
                )
                return 1

        print(f"Installing '{name_or_url}'...")
        record = installer.install(
            name_or_url,
            install_deps=not args.no_deps,
            force=args.force,
        )

        print(f"\n  Installed: {record.name}")
        if record.commit:
            print(f"  Commit: {record.commit[:12]}")
        if record.deps_installed:
            print(
                f"  Dependencies installed: "
                f"{', '.join(record.deps_installed)}"
            )
        print(
            "\n  Restart strawberry-cli to load the new skill."
        )
        return 0

    except FileExistsError as e:
        print(f"Error: {e}")
        return 1
    except ValueError as e:
        print(f"Error: {e}")
        return 1
    except RuntimeError as e:
        print(f"Error: {e}")
        return 1


def cmd_uninstall(args: argparse.Namespace) -> int:
    """Uninstall a skill."""
    installer, _catalog = _make_installer(args.config)
    name = args.name

    record = installer.get_record(name)
    skills_dir, _, _ = _resolve_paths(args.config)
    skill_dir = skills_dir / name

    if not record and not skill_dir.exists():
        print(f"Skill '{name}' is not installed.")
        return 1

    # Confirm unless --yes
    if not args.yes:
        prompt = f"Uninstall '{name}'?"
        if record and record.deps_installed and args.remove_deps:
            prompt += (
                f" (will also remove: "
                f"{', '.join(record.deps_installed)})"
            )
        prompt += " [y/N] "
        answer = input(prompt).strip().lower()
        if answer not in ("y", "yes"):
            print("Cancelled.")
            return 0

    removed = installer.uninstall(name, remove_deps=args.remove_deps)
    if removed:
        print(f"Uninstalled '{name}'.")
    else:
        print(f"Failed to uninstall '{name}'.")
        return 1
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    """Update an installed skill."""
    installer, _catalog = _make_installer(args.config)

    if args.all:
        records = installer.list_installed()
        if not records:
            print("No skills installed via the store.")
            return 0

        print(f"Updating {len(records)} skill(s)...\n")
        failures = 0
        for rec in records:
            try:
                updated = installer.update(
                    rec.name, install_deps=not args.no_deps,
                )
                if updated:
                    print(f"  {rec.name}: updated to {updated.commit[:12]}")
                else:
                    print(f"  {rec.name}: skipped (not a git repo)")
            except RuntimeError as e:
                print(f"  {rec.name}: FAILED ({e})")
                failures += 1

        if failures:
            print(f"\n{failures} skill(s) failed to update.")
            return 1
        print("\nAll skills updated.")
        return 0

    # Single skill update
    name = args.name
    if not name:
        print("Usage: strawberry-cli store update <name> or --all")
        return 1

    try:
        updated = installer.update(name, install_deps=not args.no_deps)
        if updated:
            print(f"Updated '{name}' to {updated.commit[:12]}.")
        else:
            print(f"Skill '{name}' not found or not a git repo.")
            return 1
    except RuntimeError as e:
        print(f"Error: {e}")
        return 1
    return 0


def cmd_installed(args: argparse.Namespace) -> int:
    """List installed skills."""
    installer, _catalog = _make_installer(args.config)
    records = installer.list_installed()

    if not records:
        print("No skills installed via the store.")
        return 0

    print(f"Installed skills ({len(records)}):\n")
    for rec in records:
        print(_format_installed(rec))
        print()
    return 0


# ── Argument parser ─────────────────────────────────────────────────


def build_store_parser() -> argparse.ArgumentParser:
    """Build the argument parser for store subcommands.

    Returns:
        Configured ArgumentParser.
    """
    parser = argparse.ArgumentParser(
        prog="strawberry-cli store",
        description="Strawberry Skill Store — browse, install, and manage skills.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Config directory path (default: config/).",
    )

    sub = parser.add_subparsers(dest="store_command")

    # list
    sub.add_parser("list", help="List all available skills in the catalog")

    # search
    p_search = sub.add_parser("search", help="Search the catalog")
    p_search.add_argument(
        "query", nargs="+", help="Search terms",
    )

    # install
    p_install = sub.add_parser(
        "install", help="Install a skill from catalog or URL",
    )
    p_install.add_argument(
        "name_or_url",
        help="Catalog skill name or git URL",
    )
    p_install.add_argument(
        "--force", "-f", action="store_true",
        help="Overwrite existing installation",
    )
    p_install.add_argument(
        "--no-deps", action="store_true",
        help="Skip dependency installation",
    )

    # uninstall
    p_uninstall = sub.add_parser("uninstall", help="Uninstall a skill")
    p_uninstall.add_argument("name", help="Skill name")
    p_uninstall.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip confirmation prompt",
    )
    p_uninstall.add_argument(
        "--remove-deps", action="store_true",
        help="Also remove pip dependencies installed for this skill",
    )

    # update
    p_update = sub.add_parser("update", help="Update an installed skill")
    p_update.add_argument(
        "name", nargs="?", default=None, help="Skill name",
    )
    p_update.add_argument(
        "--all", "-a", action="store_true",
        help="Update all installed skills",
    )
    p_update.add_argument(
        "--no-deps", action="store_true",
        help="Skip dependency re-check",
    )

    # installed
    sub.add_parser(
        "installed", help="List skills installed via the store",
    )

    return parser


def run_store_cli(argv: List[str] | None = None) -> int:
    """Entry point for the store CLI.

    Args:
        argv: Command line arguments (after 'store'). None = sys.argv.

    Returns:
        Exit code.
    """
    parser = build_store_parser()
    args = parser.parse_args(argv)

    if not args.store_command:
        parser.print_help()
        return 0

    handlers = {
        "list": cmd_list,
        "search": cmd_search,
        "install": cmd_install,
        "uninstall": cmd_uninstall,
        "update": cmd_update,
        "installed": cmd_installed,
    }

    handler = handlers.get(args.store_command)
    if handler:
        return handler(args)

    parser.print_help()
    return 1

"""Skill installer — clone, install deps, track installs, uninstall."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from strawberry.skills.store.catalog import SkillCatalog
from strawberry.skills.store.models import CatalogEntry, InstalledSkill

logger = logging.getLogger(__name__)

# Filename for tracking installed skills
_INSTALL_RECORD_FILE = "installed_skills.yaml"


class SkillInstaller:
    """Installs, updates, and uninstalls skills.

    Args:
        skills_dir: Directory where skills are installed (e.g. ``skills/``).
        config_dir: Directory for install tracking (e.g. ``config/``).
        catalog: Optional SkillCatalog for name-based installs.
        venv_python: Path to the venv Python interpreter for pip installs.
            Defaults to the current interpreter.
    """

    def __init__(
        self,
        skills_dir: Path,
        config_dir: Path,
        catalog: Optional[SkillCatalog] = None,
        venv_python: Optional[Path] = None,
    ):
        self._skills_dir = Path(skills_dir)
        self._config_dir = Path(config_dir)
        self._catalog = catalog
        self._venv_python = Path(venv_python) if venv_python else Path(sys.executable)
        self._record_path = self._config_dir / _INSTALL_RECORD_FILE

    # ── Public API ──────────────────────────────────────────────────

    def install(
        self,
        name_or_url: str,
        install_deps: bool = True,
        force: bool = False,
    ) -> InstalledSkill:
        """Install a skill from the catalog or a custom git URL.

        Args:
            name_or_url: Catalog skill name or a git URL.
            install_deps: If True, install detected dependencies.
            force: If True, overwrite existing installation.

        Returns:
            InstalledSkill record.

        Raises:
            ValueError: If the skill name is not found in the catalog.
            FileExistsError: If the skill is already installed and force=False.
            RuntimeError: If git clone or pip install fails.
        """
        entry, git_url, from_catalog = self._resolve_source(name_or_url)
        name = entry.name if entry else self._name_from_url(git_url)

        target_dir = self._skills_dir / name
        if target_dir.exists():
            if not force:
                raise FileExistsError(
                    f"Skill '{name}' already exists at {target_dir}. "
                    f"Use --force to overwrite."
                )
            logger.info("Removing existing installation: %s", target_dir)
            shutil.rmtree(target_dir)

        # Clone the repo
        version = entry.version if entry else "main"
        commit = self._git_clone(git_url, target_dir, version)

        # Detect and install dependencies
        deps_installed: List[str] = []
        all_deps = self._detect_deps(target_dir, entry)
        if all_deps and install_deps:
            deps_installed = self._pip_install(all_deps)

        # Save install record
        record = InstalledSkill(
            name=name,
            source_url=git_url,
            commit=commit,
            installed_at=datetime.now().isoformat(),
            deps_installed=deps_installed,
            from_catalog=from_catalog,
            version=version,
        )
        self._save_record(record)

        logger.info("Installed skill '%s' from %s", name, git_url)
        return record

    def uninstall(self, name: str, remove_deps: bool = False) -> bool:
        """Uninstall a skill by name.

        Removes the skill directory and its install record.
        Optionally removes pip dependencies that were installed for it.

        Args:
            name: Skill folder name.
            remove_deps: If True, pip-uninstall dependencies that were
                installed for this skill (only if no other skill uses them).

        Returns:
            True if the skill was found and removed.
        """
        target_dir = self._skills_dir / name
        record = self._get_record(name)

        if not target_dir.exists() and not record:
            logger.warning("Skill '%s' not found", name)
            return False

        # Remove the directory
        if target_dir.exists():
            shutil.rmtree(target_dir)
            logger.info("Removed skill directory: %s", target_dir)

        # Optionally remove deps
        if remove_deps and record and record.deps_installed:
            # Only remove deps not used by other installed skills
            other_deps = self._deps_used_by_others(name)
            removable = [d for d in record.deps_installed if d not in other_deps]
            if removable:
                self._pip_uninstall(removable)

        # Remove install record
        self._remove_record(name)

        logger.info("Uninstalled skill '%s'", name)
        return True

    def update(self, name: str, install_deps: bool = True) -> Optional[InstalledSkill]:
        """Update an installed skill by pulling latest changes.

        Args:
            name: Skill folder name.
            install_deps: If True, re-check and install new dependencies.

        Returns:
            Updated InstalledSkill record, or None if not installed.
        """
        target_dir = self._skills_dir / name
        record = self._get_record(name)

        if not target_dir.exists():
            logger.warning("Skill '%s' not found at %s", name, target_dir)
            return None

        if not (target_dir / ".git").exists():
            logger.warning(
                "Skill '%s' is not a git repo — cannot update. "
                "Re-install with `store install --force %s`.",
                name, name,
            )
            return None

        # Git pull
        new_commit = self._git_pull(target_dir)

        # Re-check deps
        deps_installed: List[str] = []
        entry = self._catalog.get(name) if self._catalog else None
        all_deps = self._detect_deps(target_dir, entry)
        if all_deps and install_deps:
            deps_installed = self._pip_install(all_deps)

        # Update record
        updated = InstalledSkill(
            name=name,
            source_url=record.source_url if record else "",
            commit=new_commit,
            installed_at=datetime.now().isoformat(),
            deps_installed=deps_installed or (record.deps_installed if record else []),
            from_catalog=record.from_catalog if record else False,
            version=record.version if record else "main",
        )
        self._save_record(updated)
        return updated

    def list_installed(self) -> List[InstalledSkill]:
        """List all skills installed via the store.

        Returns:
            List of InstalledSkill records.
        """
        records = self._load_all_records()
        return list(records.values())

    def get_record(self, name: str) -> Optional[InstalledSkill]:
        """Get the install record for a skill.

        Args:
            name: Skill name.

        Returns:
            InstalledSkill or None.
        """
        return self._get_record(name)

    # ── Source resolution ───────────────────────────────────────────

    def _resolve_source(
        self, name_or_url: str,
    ) -> Tuple[Optional[CatalogEntry], str, bool]:
        """Resolve a name or URL to a git URL.

        Returns:
            (catalog_entry_or_None, git_url, from_catalog)
        """
        # If it looks like a URL, use it directly
        if self._is_url(name_or_url):
            return None, name_or_url, False

        # Try catalog lookup
        if self._catalog:
            entry = self._catalog.get(name_or_url)
            if entry:
                return entry, entry.git_url, True

        raise ValueError(
            f"'{name_or_url}' is not a valid URL and was not found in the catalog. "
            f"Use a git URL or install from the catalog."
        )

    @staticmethod
    def _is_url(value: str) -> bool:
        """Check if a string looks like a git URL or local path."""
        return (
            value.startswith("http://")
            or value.startswith("https://")
            or value.startswith("git@")
            or value.startswith("file://")
            or value.endswith(".git")
            or Path(value).is_dir()  # Local filesystem path
        )

    @staticmethod
    def _name_from_url(url: str) -> str:
        """Extract a skill name from a git URL.

        Examples:
            https://github.com/user/weather_skill.git -> weather_skill
            https://github.com/user/weather-skill -> weather_skill
        """
        # Strip trailing .git and slashes
        clean = url.rstrip("/")
        if clean.endswith(".git"):
            clean = clean[:-4]

        # Take the last path segment
        name = clean.rsplit("/", 1)[-1]

        # Normalize: replace hyphens with underscores
        name = name.replace("-", "_")

        return name

    # ── Git operations ──────────────────────────────────────────────

    def _git_clone(self, url: str, target: Path, branch: str = "main") -> str:
        """Clone a git repo into the target directory.

        Args:
            url: Git URL.
            target: Destination directory.
            branch: Branch or tag to clone.

        Returns:
            Commit hash of the cloned repo.

        Raises:
            RuntimeError: If git is not available or clone fails.
        """
        self._check_git_available()

        cmd = [
            "git", "clone",
            "--depth", "1",
            "--branch", branch,
            url,
            str(target),
        ]
        logger.info("Cloning %s (branch=%s) -> %s", url, branch, target)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            # If branch clone fails, try without --branch (default branch)
            stderr_lower = result.stderr.lower()
            if "not found" in stderr_lower or "could not find" in stderr_lower:
                logger.warning(
                    "Branch '%s' not found, trying default branch", branch,
                )
                cmd_fallback = [
                    "git", "clone", "--depth", "1", url, str(target),
                ]
                result = subprocess.run(
                    cmd_fallback,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        f"git clone failed: {result.stderr.strip()}"
                    )
            else:
                raise RuntimeError(
                    f"git clone failed: {result.stderr.strip()}"
                )

        # Get the commit hash
        return self._git_rev_parse(target)

    def _git_pull(self, repo_dir: Path) -> str:
        """Pull latest changes in a git repo.

        Args:
            repo_dir: Path to the repo.

        Returns:
            New commit hash.
        """
        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            capture_output=True,
            text=True,
            cwd=str(repo_dir),
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git pull failed in {repo_dir}: {result.stderr.strip()}"
            )
        return self._git_rev_parse(repo_dir)

    @staticmethod
    def _git_rev_parse(repo_dir: Path) -> str:
        """Get the current commit hash of a repo."""
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(repo_dir),
            timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"

    @staticmethod
    def _check_git_available() -> None:
        """Check that git is available on the system."""
        try:
            subprocess.run(
                ["git", "--version"],
                capture_output=True,
                timeout=10,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "git is not installed. Install git to use the skill store, "
                "or install skills manually by cloning into the skills/ directory."
            )

    # ── Dependency detection and installation ───────────────────────

    def _detect_deps(
        self, skill_dir: Path, entry: Optional[CatalogEntry] = None,
    ) -> List[str]:
        """Detect dependencies for a skill.

        Checks (in priority order):
        1. Catalog entry's ``requires`` field
        2. ``requirements.txt`` in the skill directory
        3. ``pyproject.toml`` [project.dependencies] in the skill directory

        Args:
            skill_dir: Path to the installed skill.
            entry: Optional catalog entry with pre-declared deps.

        Returns:
            List of pip-installable package specifiers.
        """
        # 1. Catalog entry
        if entry and entry.requires:
            return list(entry.requires)

        # 2. requirements.txt
        req_file = skill_dir / "requirements.txt"
        if req_file.exists():
            return self._parse_requirements_txt(req_file)

        # 3. pyproject.toml
        pyproject = skill_dir / "pyproject.toml"
        if pyproject.exists():
            return self._parse_pyproject_deps(pyproject)

        return []

    @staticmethod
    def _parse_requirements_txt(path: Path) -> List[str]:
        """Parse a requirements.txt file.

        Args:
            path: Path to requirements.txt.

        Returns:
            List of non-comment, non-empty lines.
        """
        deps = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            # Skip comments, empty lines, and options
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            deps.append(line)
        return deps

    @staticmethod
    def _parse_pyproject_deps(path: Path) -> List[str]:
        """Parse dependencies from a pyproject.toml file.

        Only reads [project.dependencies] — ignores optional deps.

        Args:
            path: Path to pyproject.toml.

        Returns:
            List of dependency specifiers.
        """
        try:
            # Use tomllib (Python 3.11+) or tomli fallback
            try:
                import tomllib
            except ImportError:
                import tomli as tomllib  # type: ignore[no-redef]

            with open(path, "rb") as f:
                data = tomllib.load(f)

            return data.get("project", {}).get("dependencies", [])
        except Exception as e:
            logger.warning("Failed to parse %s: %s", path, e)
            return []

    def _pip_install(self, packages: List[str]) -> List[str]:
        """Install packages into the venv via pip.

        Args:
            packages: List of pip-installable package specifiers.

        Returns:
            List of packages that were actually installed (may exclude
            already-installed ones).

        Raises:
            RuntimeError: If pip install fails.
        """
        if not packages:
            return []

        cmd = [
            str(self._venv_python), "-m", "pip", "install",
            "--quiet", *packages,
        ]
        logger.info("Installing dependencies: %s", ", ".join(packages))

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"pip install failed:\n{result.stderr.strip()}"
            )

        return packages

    def _pip_uninstall(self, packages: List[str]) -> None:
        """Uninstall packages via pip.

        Args:
            packages: List of package names to remove.
        """
        if not packages:
            return

        cmd = [
            str(self._venv_python), "-m", "pip", "uninstall",
            "-y", "--quiet", *packages,
        ]
        logger.info("Removing dependencies: %s", ", ".join(packages))

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.warning("pip uninstall had errors: %s", result.stderr.strip())

    # ── Install record persistence ──────────────────────────────────

    def _load_all_records(self) -> Dict[str, InstalledSkill]:
        """Load all install records from disk."""
        if not self._record_path.exists():
            return {}

        with open(self._record_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        records: Dict[str, InstalledSkill] = {}
        for name, data in raw.get("installed", {}).items():
            if not isinstance(data, dict):
                continue
            records[name] = InstalledSkill(
                name=name,
                source_url=data.get("source_url", ""),
                commit=data.get("commit", ""),
                installed_at=data.get("installed_at", ""),
                deps_installed=data.get("deps_installed", []),
                from_catalog=data.get("from_catalog", False),
                version=data.get("version"),
            )
        return records

    def _get_record(self, name: str) -> Optional[InstalledSkill]:
        """Get a single install record by name."""
        return self._load_all_records().get(name)

    def _save_record(self, record: InstalledSkill) -> None:
        """Save or update a single install record."""
        records = self._load_all_records()
        records[record.name] = record
        self._write_records(records)

    def _remove_record(self, name: str) -> None:
        """Remove an install record by name."""
        records = self._load_all_records()
        records.pop(name, None)
        self._write_records(records)

    def _write_records(self, records: Dict[str, InstalledSkill]) -> None:
        """Write all install records to disk."""
        self._config_dir.mkdir(parents=True, exist_ok=True)

        data: Dict[str, Any] = {"installed": {}}
        for name, rec in records.items():
            data["installed"][name] = {
                "source_url": rec.source_url,
                "commit": rec.commit,
                "installed_at": rec.installed_at,
                "deps_installed": rec.deps_installed,
                "from_catalog": rec.from_catalog,
                "version": rec.version,
            }

        with open(self._record_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def _deps_used_by_others(self, exclude_name: str) -> set:
        """Get the set of deps used by skills other than the given one.

        Args:
            exclude_name: Skill name to exclude.

        Returns:
            Set of package names used by other installed skills.
        """
        records = self._load_all_records()
        other_deps: set = set()
        for name, rec in records.items():
            if name == exclude_name:
                continue
            other_deps.update(rec.deps_installed)
        return other_deps

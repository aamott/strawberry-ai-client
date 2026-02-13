"""Skill catalog — load, search, and list available skills."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from strawberry.skills.store.models import CatalogEntry

logger = logging.getLogger(__name__)

# Default catalog file ships with the store package
_DEFAULT_CATALOG_PATH = Path(__file__).parent / "skill_catalog.yaml"


class SkillCatalog:
    """Loads and searches the curated skill catalog.

    The catalog is a YAML file containing a list of skill entries.
    Users can also point to a custom catalog file.

    Args:
        catalog_path: Path to the catalog YAML file.
            Defaults to ``data/skill_catalog.yaml`` in the project root.
    """

    def __init__(self, catalog_path: Optional[Path] = None):
        self._path = Path(catalog_path) if catalog_path else _DEFAULT_CATALOG_PATH
        self._entries: Dict[str, CatalogEntry] = {}
        self._loaded = False

    @property
    def path(self) -> Path:
        """Path to the catalog file."""
        return self._path

    def load(self) -> int:
        """Load the catalog from disk.

        Returns:
            Number of entries loaded.

        Raises:
            FileNotFoundError: If the catalog file doesn't exist.
        """
        if not self._path.exists():
            raise FileNotFoundError(f"Catalog not found: {self._path}")

        with open(self._path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        skills_list = raw.get("skills", [])
        self._entries.clear()

        for item in skills_list:
            if not isinstance(item, dict):
                logger.warning("Skipping non-dict catalog entry: %s", item)
                continue

            name = item.get("name", "")
            if not name:
                logger.warning("Skipping catalog entry without name: %s", item)
                continue

            entry = CatalogEntry(
                name=name,
                git_url=item.get("git_url", ""),
                description=item.get("description", ""),
                author=item.get("author", ""),
                tags=item.get("tags", []),
                version=item.get("version", "main"),
                requires=item.get("requires", []),
            )
            self._entries[name] = entry

        self._loaded = True
        logger.info("Loaded %d catalog entries from %s", len(self._entries), self._path)
        return len(self._entries)

    def _ensure_loaded(self) -> None:
        """Load the catalog if not already loaded."""
        if not self._loaded:
            self.load()

    def search(self, query: str) -> List[CatalogEntry]:
        """Search the catalog by keyword.

        Args:
            query: Space-separated search terms.

        Returns:
            List of matching CatalogEntry objects.
        """
        self._ensure_loaded()
        if not query or not query.strip():
            return self.list_all()
        return [e for e in self._entries.values() if e.matches(query)]

    def list_all(self) -> List[CatalogEntry]:
        """List all catalog entries.

        Returns:
            All CatalogEntry objects in the catalog.
        """
        self._ensure_loaded()
        return list(self._entries.values())

    def get(self, name: str) -> Optional[CatalogEntry]:
        """Get a catalog entry by name.

        Args:
            name: Skill name (must match exactly).

        Returns:
            CatalogEntry or None.
        """
        self._ensure_loaded()
        return self._entries.get(name)

    def __len__(self) -> int:
        self._ensure_loaded()
        return len(self._entries)

"""Data models for the skill store."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class CatalogEntry:
    """A skill available in the catalog.

    Attributes:
        name: Short identifier (matches the repo folder name in skills/).
        git_url: Git clone URL.
        description: Human-readable description.
        author: Author name or GitHub handle.
        tags: Searchable tags (e.g. ["weather", "api", "location"]).
        version: Optional pinned version (git tag or branch).
        requires: Python package dependencies (pip-installable names).
    """

    name: str
    git_url: str
    description: str = ""
    author: str = ""
    tags: List[str] = field(default_factory=list)
    version: str = "main"
    requires: List[str] = field(default_factory=list)

    def matches(self, query: str) -> bool:
        """Check if this entry matches a search query.

        Searches name, description, author, and tags (case-insensitive).

        Args:
            query: Space-separated search terms. All terms must match.

        Returns:
            True if all query terms match at least one field.
        """
        terms = query.lower().split()
        if not terms:
            return True

        searchable = " ".join([
            self.name.lower(),
            self.description.lower(),
            self.author.lower(),
            " ".join(t.lower() for t in self.tags),
        ])

        return all(term in searchable for term in terms)


@dataclass
class InstalledSkill:
    """Record of a skill installed via the store.

    Attributes:
        name: Skill folder name (matches CatalogEntry.name).
        source_url: Git URL or custom URL used to install.
        commit: Git commit hash at install time.
        installed_at: ISO timestamp of installation.
        deps_installed: List of pip packages installed for this skill.
        from_catalog: Whether this was installed from the curated catalog.
    """

    name: str
    source_url: str
    commit: str = ""
    installed_at: str = field(default_factory=lambda: datetime.now().isoformat())
    deps_installed: List[str] = field(default_factory=list)
    from_catalog: bool = False
    version: Optional[str] = None

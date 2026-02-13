"""Proxy classes for LLM-generated code to access skills.

These proxies provide the ``device.*`` and ``devices.*`` / ``device_manager.*``
namespaces that the LLM uses inside ``python_exec`` calls.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from .loader import SkillLoader

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def normalize_device_name(name: str) -> str:
    """Normalize a device name for consistent routing.

    Transforms device names into a canonical form:
    - Lowercased
    - Spaces/hyphens converted to underscores
    - Special characters removed
    - Unicode normalized to ASCII equivalents

    This implementation must stay in sync with the Hub's
    ``hub.utils.normalize_device_name``.  The canonical test vectors
    live in ``docs/test-fixtures/normalize_device_name.json``.

    Args:
        name: Raw device name (display name).

    Returns:
        Normalized name suitable for routing.
    """
    if not name:
        return ""

    # Normalize unicode (é -> e, ü -> u, etc.)
    normalized = unicodedata.normalize("NFKD", name)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")

    # Lowercase
    normalized = normalized.lower()

    # Replace spaces and hyphens with underscores
    normalized = re.sub(r"[\s\-]+", "_", normalized)

    # Remove non-alphanumeric characters (except underscores)
    normalized = re.sub(r"[^a-z0-9_]", "", normalized)

    # Collapse multiple underscores
    normalized = re.sub(r"_+", "_", normalized)

    # Strip leading/trailing underscores
    normalized = normalized.strip("_")

    return normalized


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SkillCallResult:
    """Result of executing a skill call."""

    success: bool
    result: Any = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Search helpers
# ---------------------------------------------------------------------------

# Common English stop words to strip from search queries.
# Only includes true noise words (articles, pronouns, filler).
# Does NOT include action verbs like "turn", "on", "off", "set", "get"
# — those are critical for smart-home skill discovery (e.g. HassTurnOn).
_SEARCH_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "to",
        "for",
        "of",
        "in",
        "it",
        "and",
        "or",
        "my",
        "me",
        "i",
        "do",
        "can",
        "you",
        "please",
        "what",
        "how",
    }
)

# Regex to split camelCase / PascalCase into separate words.
# "HassTurnOn" → ["Hass", "Turn", "On"]
_CAMEL_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _tokenize_to_words(text: str) -> frozenset[str]:
    """Tokenize text into a set of lowercase words.

    Handles camelCase splitting (HassTurnOn → {hass, turn, on}),
    underscores, and general punctuation so that word-boundary
    matching works correctly (e.g. 'on' won't match 'information').

    Args:
        text: Raw searchable text (names, signatures, docstrings).

    Returns:
        Frozen set of lowercase word tokens.
    """
    # Split camelCase first, then split on non-alpha boundaries
    expanded = _CAMEL_RE.sub(" ", text)
    tokens = re.split(r"[^a-zA-Z0-9]+", expanded.lower())
    return frozenset(t for t in tokens if t)


# ---------------------------------------------------------------------------
# Local device proxies
# ---------------------------------------------------------------------------


class DeviceProxy:
    """Proxy object for accessing skills from LLM-generated code.

    Provides:
    - device.search_skills("query") - Find skills by keyword
    - device.describe_function("SkillName.method") - Get function details
    - device.SkillName.method_name(args) - Call a skill
    """

    def __init__(self, loader: SkillLoader):
        """Initialize the device proxy.

        Args:
            loader: Skill loader used to resolve skills.
        """
        self._loader = loader

    def search_skills(
        self, query: str = "", device_limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Search for skills by keyword.

        Splits the query into words and matches if **any** word appears
        in the method name, skill name, signature, or docstring.  This
        makes multi-word queries like "react documentation" find results
        that match on "documentation" alone.

        Args:
            query: Search term (matches name, signature, docstring)
            device_limit: Ignored for local-only mode

        Returns:
            List of matching skills with path, signature, summary
        """
        query_words = self._parse_query_words(query)
        candidates = self._build_search_candidates(query_words)
        matched = self._match_candidates(candidates, query_words)

        results = []
        for skill, method in matched:
            summary = ""
            if method.docstring:
                summary = method.docstring.split("\n")[0].strip()
            results.append(
                {
                    "path": f"{skill.name}.{method.name}",
                    "signature": method.signature,
                    "summary": summary,
                }
            )
        return results

    @staticmethod
    def _parse_query_words(query: str) -> list[str]:
        """Parse a query into search words, stripping stop words."""
        raw_words = query.lower().split() if query else []
        query_words = [w for w in raw_words if w not in _SEARCH_STOP_WORDS]
        # Fall back to original words if stop-word stripping removed everything
        if not query_words and raw_words:
            query_words = raw_words
        return query_words

    def _build_search_candidates(
        self,
        query_words: list[str],
    ) -> list[tuple]:
        """Build (skill, method, word_set) triples."""
        candidates: list[tuple] = []
        for skill in self._loader.get_all_skills():
            # Include class summary (MCP keyword aggregation) if present
            class_summary = getattr(
                skill.class_obj, "__class_summary__", ""
            )
            for method in skill.methods:
                if not query_words:
                    candidates.append((skill, method, True))
                else:
                    raw = (
                        f"{method.name} {skill.name} "
                        f"{method.signature} "
                        f"{method.docstring or ''} "
                        f"{class_summary}"
                    )
                    word_set = _tokenize_to_words(raw)
                    candidates.append((skill, method, word_set))
        return candidates

    @staticmethod
    def _match_candidates(
        candidates: list[tuple],
        query_words: list[str],
    ) -> list[tuple]:
        """Match candidates against query words (all-words first, then any-word).

        Uses word-set membership (not substring) so 'on' doesn't match
        'information'.
        """
        if not query_words:
            return [(s, m) for s, m, _ in candidates]

        matched = [
            (s, m)
            for s, m, ws in candidates
            if ws is True or all(w in ws for w in query_words)
        ]
        if not matched:
            matched = [
                (s, m)
                for s, m, ws in candidates
                if ws is True or any(w in ws for w in query_words)
            ]
        return matched

    def describe_function(self, path: str) -> str:
        """Get full function details including docstring.

        Args:
            path: "SkillName.method_name"

        Returns:
            Full function signature with docstring
        """
        # Import here to avoid circular dependency
        from .prompt import build_example_call

        parts = path.split(".")
        if len(parts) != 2:
            return f"Error: Invalid path '{path}'. Use format 'SkillName.method_name'"

        skill_name, method_name = parts
        skill = self._loader.get_skill(skill_name)

        if not skill:
            return f"Error: Skill '{skill_name}' not found"

        for method in skill.methods:
            if method.name == method_name:
                doc = method.docstring or "No description available"
                example = build_example_call(skill_name, method)
                result = f'def {method.signature}:\n    """\n    {doc}\n    """'
                if example:
                    result += f'\n\nExample:\n  python_exec(code="{example}")'
                return result

        return f"Error: Method '{method_name}' not found in {skill_name}"

    def __getattr__(self, name: str):
        """Get a skill class by name for direct calls."""
        # Don't intercept private attributes
        if name.startswith("_"):
            raise AttributeError(name)

        skill = self._loader.get_skill(name)
        if skill is None:
            # Get list of available skills for helpful error
            available = [s.name for s in self._loader.get_all_skills()]
            available_str = ", ".join(available) if available else "none loaded"
            raise AttributeError(
                f"Skill '{name}' not found. "
                f"Available skills: {available_str}. "
                f"Use device.search_skills() to search."
            )
        return SkillProxy(self._loader, name)


class SkillProxy:
    """Proxy for a specific skill class."""

    def __init__(self, loader: SkillLoader, skill_name: str):
        """Initialize a proxy for a single skill.

        Args:
            loader: Skill loader used to resolve methods.
            skill_name: Skill class name.
        """
        self._loader = loader
        self._skill_name = skill_name

    def __getattr__(self, name: str):
        """Get a method that calls the actual skill."""

        def method_wrapper(*args, **kwargs):
            return self._loader.call_method(self._skill_name, name, *args, **kwargs)

        return method_wrapper

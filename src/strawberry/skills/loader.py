"""Skill discovery and loading from Python files."""

import importlib.util
import inspect
import logging
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SkillLoadFailure:
    """Record of a skill that failed to load."""
    source: str  # file path or repo name
    error: str   # human-readable error message


@dataclass
class SkillMethod:
    """Information about a skill method."""
    name: str
    signature: str
    docstring: Optional[str]
    callable: Callable

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API."""
        return {
            "function_name": self.name,
            "signature": self.signature,
            "docstring": self.docstring,
        }


@dataclass
class SkillInfo:
    """Information about a loaded skill class."""
    name: str
    class_obj: type
    methods: List[SkillMethod] = field(default_factory=list)
    module_path: Optional[Path] = None
    instance: Optional[Any] = None  # Instantiated skill object

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API."""
        return {
            "class_name": self.name,
            "methods": [m.to_dict() for m in self.methods],
        }

    def get_registration_data(self) -> List[Dict[str, Any]]:
        """Get data for Hub registration."""
        return [
            {
                "class_name": self.name,
                "function_name": m.name,
                "signature": m.signature,
                "docstring": m.docstring,
            }
            for m in self.methods
        ]


class SkillLoader:
    """Loads skill classes from Python files.

    Skills are Python classes that:
    - End with 'Skill' in the name (e.g., MusicControlSkill)
    - Have public methods that can be called by the LLM
    - Methods starting with '_' are considered private and ignored

    Example skill file (music_skill.py):
    ```python
    class MusicControlSkill:
        '''Controls music playback.'''

        def play_song(self, name: str) -> bool:
            '''Play a song by name.'''
            # Implementation...
            return True

        def stop(self) -> None:
            '''Stop playback.'''
            pass
    ```
    """

    def __init__(self, skills_path: Path):
        """Initialize skill loader.

        Args:
            skills_path: Directory containing skill Python files
        """
        self.skills_path = Path(skills_path)
        self._skills: Dict[str, SkillInfo] = {}
        self._instances: Dict[str, Any] = {}
        self._failures: List[SkillLoadFailure] = []

        self._repo_namespace_root = "strawberry_skillrepos"

    def load_all(self) -> List[SkillInfo]:
        """Load all skills from the skills directory.

        Returns:
            List of loaded SkillInfo objects
        """
        self._skills.clear()
        self._instances.clear()
        self._failures.clear()

        if not self.skills_path.exists():
            logger.warning(f"Skills directory does not exist: {self.skills_path}")
            return []

        if not self.skills_path.is_dir():
            logger.warning(f"Skills path is not a directory: {self.skills_path}")
            return []

        # Find all repo-style skills: skills/<repo_name>/<entrypoint>.py
        for repo_dir in self.skills_path.iterdir():
            if not repo_dir.is_dir():
                continue
            if repo_dir.name.startswith("."):
                continue
            if repo_dir.name == "__pycache__":
                continue

            entrypoint = self._find_repo_entrypoint(repo_dir)
            if entrypoint is None:
                continue

            try:
                skills = self._load_repo_entrypoint(repo_dir, entrypoint)
                for skill in skills:
                    if skill.name in self._skills:
                        logger.error(
                            "Duplicate skill class name '%s' found in %s; "
                            "already loaded from %s. Skipping duplicate.",
                            skill.name,
                            str(entrypoint),
                            str(self._skills[skill.name].module_path),
                        )
                        continue
                    self._skills[skill.name] = skill
                    logger.info(
                        "Loaded repo skill: %s (%d methods)",
                        skill.name,
                        len(skill.methods),
                    )
            except Exception as e:
                logger.error(f"Failed to load repo skill from {entrypoint}: {e}")
                self._failures.append(SkillLoadFailure(
                    source=str(repo_dir.name),
                    error=str(e),
                ))

        # Find all top-level Python files
        for py_file in self.skills_path.glob("*.py"):
            if py_file.name.startswith("_"):
                continue

            try:
                skills = self._load_file(py_file)
                for skill in skills:
                    if skill.name in self._skills:
                        logger.error(
                            "Duplicate skill class name '%s' found in %s; "
                            "already loaded from %s. Skipping duplicate.",
                            skill.name,
                            str(py_file),
                            str(self._skills[skill.name].module_path),
                        )
                        continue
                    self._skills[skill.name] = skill
                    logger.info(
                        "Loaded skill: %s (%d methods)",
                        skill.name,
                        len(skill.methods),
                    )
            except Exception as e:
                logger.error(f"Failed to load {py_file}: {e}")
                self._failures.append(SkillLoadFailure(
                    source=py_file.name,
                    error=str(e),
                ))

        return list(self._skills.values())

    def _find_repo_entrypoint(self, repo_dir: Path) -> Optional[Path]:
        """Find the entrypoint Python file for a repo-style skill.

        Supported (first match wins):
        - skill.py
        - <repo_name>.py
        - main.py
        - __init__.py
        """
        candidates = [
            repo_dir / "skill.py",
            repo_dir / f"{repo_dir.name}.py",
            repo_dir / "main.py",
            repo_dir / "__init__.py",
        ]

        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                if candidate.name.startswith("_"):
                    continue
                return candidate
        return None

    def _ensure_repo_namespace_root(self) -> None:
        """Ensure the repo namespace root module exists in sys.modules."""
        if self._repo_namespace_root in sys.modules:
            return

        root = types.ModuleType(self._repo_namespace_root)
        root.__path__ = []  # type: ignore[attr-defined]
        sys.modules[self._repo_namespace_root] = root

    def _load_repo_entrypoint(self, repo_dir: Path, entrypoint: Path) -> List[SkillInfo]:
        """Load skills from a repo entrypoint.

        The entrypoint is loaded as a unique package namespace:
        strawberry_skillrepos.<repo_name>

        This enables safe relative imports inside the repo, e.g.:
        - from . import helpers
        - from .my_pkg.utils import foo
        """
        self._ensure_repo_namespace_root()

        repo_name = repo_dir.name
        module_name = f"{self._repo_namespace_root}.{repo_name}"

        # Load as a package so relative imports work.
        spec = importlib.util.spec_from_file_location(
            module_name,
            entrypoint,
            submodule_search_locations=[str(repo_dir)],
        )

        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load spec for {entrypoint}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        skills: List[SkillInfo] = []
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ == module_name and name.endswith("Skill"):
                skill_info = self._extract_skill_info(name, obj, entrypoint)
                if skill_info.methods:
                    skills.append(skill_info)
        return skills

    def _load_file(self, file_path: Path) -> List[SkillInfo]:
        """Load skills from a single Python file.

        Args:
            file_path: Path to Python file

        Returns:
            List of SkillInfo objects found in the file
        """
        # Load module dynamically
        module_name = f"skills.{file_path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, file_path)

        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load spec for {file_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Find skill classes
        skills = []
        for name, obj in inspect.getmembers(module, inspect.isclass):
            # Only classes defined in this module and ending with 'Skill'
            if obj.__module__ == module_name and name.endswith("Skill"):
                skill_info = self._extract_skill_info(name, obj, file_path)
                if skill_info.methods:  # Only include if it has methods
                    skills.append(skill_info)

        return skills

    def _extract_skill_info(self, name: str, cls: type, file_path: Path) -> SkillInfo:
        """Extract information from a skill class.

        Args:
            name: Class name
            cls: Class object
            file_path: Source file path

        Returns:
            SkillInfo with methods
        """
        methods = []

        for method_name, method in inspect.getmembers(cls, inspect.isfunction):
            # Skip private methods
            if method_name.startswith("_"):
                continue

            # Get signature
            try:
                sig = inspect.signature(method)
                # Remove 'self' parameter for display
                params = [
                    p for name, p in sig.parameters.items()
                    if name != "self"
                ]
                new_sig = sig.replace(parameters=params)
                sig_str = f"{method_name}{new_sig}"
            except ValueError:
                sig_str = f"{method_name}(...)"

            # Get docstring
            docstring = inspect.getdoc(method)

            methods.append(SkillMethod(
                name=method_name,
                signature=sig_str,
                docstring=docstring,
                callable=method,
            ))

        # Create instance of the skill class
        try:
            instance = cls()
        except Exception as e:
            logger.warning(f"Failed to instantiate {name}: {e}")
            instance = None

        return SkillInfo(
            name=name,
            class_obj=cls,
            methods=methods,
            module_path=file_path,
            instance=instance,
        )

    def get_skill(self, name: str) -> Optional[SkillInfo]:
        """Get a loaded skill by name."""
        return self._skills.get(name)

    def get_instance(self, skill_name: str) -> Any:
        """Get or create an instance of a skill class.

        Skill instances are cached for reuse.
        """
        if skill_name not in self._instances:
            skill = self._skills.get(skill_name)
            if skill:
                self._instances[skill_name] = skill.class_obj()
        return self._instances.get(skill_name)

    @property
    def failures(self) -> List[SkillLoadFailure]:
        """Get the list of skill load failures from the last load_all()."""
        return list(self._failures)

    def get_all_skills(self) -> List[SkillInfo]:
        """Get all loaded skills."""
        return list(self._skills.values())

    def get_registration_data(self) -> List[Dict[str, Any]]:
        """Get data for registering all skills with Hub.

        Returns:
            List of skill method dictionaries ready for API
        """
        data = []
        for skill in self._skills.values():
            data.extend(skill.get_registration_data())
        return data

    def call_method(
        self,
        skill_name: str,
        method_name: str,
        *args,
        **kwargs
    ) -> Any:
        """Call a method on a skill.

        Args:
            skill_name: Name of the skill class
            method_name: Name of the method to call
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Method return value

        Raises:
            ValueError: If skill or method not found
        """
        instance = self.get_instance(skill_name)
        if instance is None:
            raise ValueError(f"Skill not found: {skill_name}")

        method = getattr(instance, method_name, None)
        if method is None or not callable(method):
            raise ValueError(f"Method not found: {skill_name}.{method_name}")

        return method(*args, **kwargs)


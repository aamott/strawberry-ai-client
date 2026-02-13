"""Skill discovery and loading from Python files."""

import importlib.util
import inspect
import logging
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

if TYPE_CHECKING:
    from ..shared.settings import SettingField, SettingsManager

logger = logging.getLogger(__name__)


@dataclass
class SkillLoadFailure:
    """Record of a skill that failed to load."""

    source: str  # file path or repo name
    error: str  # human-readable error message


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
    # Settings schema discovered from the module's SETTINGS_SCHEMA attribute
    settings_schema: Optional[List["SettingField"]] = None
    # Repo directory name (e.g. "weather_skill") for namespace derivation
    repo_name: Optional[str] = None

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

    def __init__(
        self,
        skills_path: Path,
        settings_manager: Optional["SettingsManager"] = None,
    ):
        """Initialize skill loader.

        Args:
            skills_path: Directory containing skill Python files.
            settings_manager: Optional SettingsManager for skill settings
                injection and schema registration.
        """
        self.skills_path = Path(skills_path)
        self._settings_manager = settings_manager
        self._skills: Dict[str, SkillInfo] = {}
        self._instances: Dict[str, Any] = {}
        self._failures: List[SkillLoadFailure] = []

        self._repo_namespace_root = "strawberry_skillrepos"

    def _register_loaded_skills(
        self,
        skills: list,
        source_label: str,
    ) -> None:
        """Register loaded skills, skipping duplicates.

        Args:
            skills: List of SkillInfo objects to register.
            source_label: Label for log messages (e.g. file path).
        """
        for skill in skills:
            if skill.name in self._skills:
                logger.error(
                    "Duplicate skill class name '%s' found in %s; "
                    "already loaded from %s. Skipping duplicate.",
                    skill.name,
                    source_label,
                    str(self._skills[skill.name].module_path),
                )
                continue
            self._skills[skill.name] = skill
            logger.info(
                "Loaded skill: %s (%d methods)",
                skill.name,
                len(skill.methods),
            )

    def load_all(
        self,
        on_skill_loaded: Optional[Callable[[str, str, float], None]] = None,
        on_skill_failed: Optional[Callable[[str, str, str], None]] = None,
    ) -> List[SkillInfo]:
        """Load all skills from the skills directory.

        Args:
            on_skill_loaded: Optional callback called after each skill loads.
                Signature: (skill_name, source, elapsed_ms).
            on_skill_failed: Optional callback called for each failed skill.
                Signature: (source, error, skill_name_if_known).

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

        # Collect repo dirs and their entrypoints.
        repo_entries: list[tuple] = []
        for repo_dir in sorted(self.skills_path.iterdir()):
            if not repo_dir.is_dir():
                continue
            if repo_dir.name.startswith(".") or repo_dir.name == "__pycache__":
                continue
            entrypoint = self._find_repo_entrypoint(repo_dir)
            if entrypoint is not None:
                repo_entries.append((repo_dir, entrypoint))

        # Split repos into deferred (async discovery) vs regular.
        deferred, regular = self._partition_repos(repo_entries)

        # Phase 1: Import deferred repos (triggers background discovery).
        for repo_dir, entrypoint in deferred:
            self._import_repo_module(repo_dir, entrypoint)

        # Phase 2: Load regular repos while deferred discovery runs.
        self._load_repo_batch(regular, on_skill_loaded, on_skill_failed)

        # Phase 3: Collect deferred repos (wait_for_discovery called inside).
        self._load_repo_batch(deferred, on_skill_loaded, on_skill_failed)

        # Phase 4: Load top-level Python files.
        self._load_top_level_files(on_skill_loaded, on_skill_failed)

        return list(self._skills.values())

    def _partition_repos(
        self, repo_entries: list[tuple],
    ) -> tuple[list[tuple], list[tuple]]:
        """Split repos into deferred (async discovery) and regular groups.

        Repos with async discovery (e.g. mcp_skill) are imported first so
        their background connections overlap with loading regular repos.

        Returns:
            (deferred, regular) tuple of repo entry lists.
        """
        deferred: list[tuple] = []
        regular: list[tuple] = []
        for repo_dir, entrypoint in repo_entries:
            if self._has_async_discovery(entrypoint):
                deferred.append((repo_dir, entrypoint))
            else:
                regular.append((repo_dir, entrypoint))
        return deferred, regular

    def _load_repo_batch(
        self,
        entries: list[tuple],
        on_skill_loaded: Optional[Callable] = None,
        on_skill_failed: Optional[Callable] = None,
    ) -> None:
        """Load a batch of repo-style skills, recording failures."""
        import time as _time

        for repo_dir, entrypoint in entries:
            t0 = _time.monotonic()
            try:
                skills = self._load_repo_entrypoint(repo_dir, entrypoint)
                self._register_loaded_skills(skills, str(entrypoint))
                elapsed_ms = (_time.monotonic() - t0) * 1000
                if on_skill_loaded:
                    for s in skills:
                        on_skill_loaded(
                            s.name, repo_dir.name, elapsed_ms,
                        )
            except Exception as e:
                logger.error(f"Failed to load repo skill from {entrypoint}: {e}")
                self._failures.append(
                    SkillLoadFailure(
                        source=str(repo_dir.name),
                        error=str(e),
                    )
                )
                if on_skill_failed:
                    on_skill_failed(
                        repo_dir.name, str(e), "",
                    )

    def _load_top_level_files(
        self,
        on_skill_loaded: Optional[Callable] = None,
        on_skill_failed: Optional[Callable] = None,
    ) -> None:
        """Load skills from top-level *.py files in the skills directory."""
        import time as _time

        for py_file in self.skills_path.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            t0 = _time.monotonic()
            try:
                skills = self._load_file(py_file)
                self._register_loaded_skills(skills, str(py_file))
                elapsed_ms = (_time.monotonic() - t0) * 1000
                if on_skill_loaded:
                    for s in skills:
                        on_skill_loaded(
                            s.name, py_file.stem, elapsed_ms,
                        )
            except Exception as e:
                logger.error(f"Failed to load {py_file}: {e}")
                self._failures.append(
                    SkillLoadFailure(
                        source=py_file.name,
                        error=str(e),
                    )
                )
                if on_skill_failed:
                    on_skill_failed(
                        py_file.stem, str(e), "",
                    )

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

    @staticmethod
    def _has_async_discovery(entrypoint: Path) -> bool:
        """Check if a repo entrypoint uses async discovery.

        A quick text scan for ``_start_discovery`` avoids importing the
        module just to inspect it.
        """
        try:
            text = entrypoint.read_text(encoding="utf-8", errors="ignore")
            return "_start_discovery" in text
        except OSError:
            return False

    def _import_repo_module(self, repo_dir: Path, entrypoint: Path) -> None:
        """Import a repo module without scanning for skill classes.

        Triggers module-level code (e.g. ``_start_discovery()``) so that
        background work can overlap with loading other repos.
        """
        self._ensure_repo_namespace_root()
        module_name = f"{self._repo_namespace_root}.{repo_dir.name}"
        if module_name in sys.modules:
            return
        spec = importlib.util.spec_from_file_location(
            module_name,
            entrypoint,
            submodule_search_locations=[str(repo_dir)],
        )
        if spec is None or spec.loader is None:
            return
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

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

        # Reuse already-imported module to avoid re-executing module-level
        # code (e.g. MCP skill discovery) which can block on network I/O.
        if module_name in sys.modules:
            module = sys.modules[module_name]
        else:
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

        # If the module exposes a wait_for_discovery() hook (e.g. MCP skill),
        # call it so that dynamically generated classes are available before
        # we scan with inspect.getmembers().  Discovery was started in the
        # background at module import time, so this just waits for it to finish.
        waiter = getattr(module, "wait_for_discovery", None)
        if callable(waiter):
            waiter()

        # Detect SETTINGS_SCHEMA on the module
        module_schema = getattr(module, "SETTINGS_SCHEMA", None)

        skills: List[SkillInfo] = []
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ == module_name and name.endswith("Skill"):
                skill_info = self._extract_skill_info(
                    name, obj, entrypoint, repo_name=repo_name,
                )
                if skill_info.methods:
                    # Attach module-level schema to first skill in the repo
                    if module_schema and not skill_info.settings_schema:
                        skill_info.settings_schema = module_schema
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

        # Detect SETTINGS_SCHEMA on the module
        module_schema = getattr(module, "SETTINGS_SCHEMA", None)
        # Derive repo name from file stem (e.g. "weather_skill" from weather_skill.py)
        derived_repo = file_path.stem

        # Find skill classes
        skills = []
        for name, obj in inspect.getmembers(module, inspect.isclass):
            # Only classes defined in this module and ending with 'Skill'
            if obj.__module__ == module_name and name.endswith("Skill"):
                skill_info = self._extract_skill_info(
                    name, obj, file_path, repo_name=derived_repo,
                )
                if skill_info.methods:  # Only include if it has methods
                    if module_schema and not skill_info.settings_schema:
                        skill_info.settings_schema = module_schema
                    skills.append(skill_info)

        return skills

    def _extract_skill_info(
        self,
        name: str,
        cls: type,
        file_path: Path,
        repo_name: Optional[str] = None,
    ) -> SkillInfo:
        """Extract information from a skill class.

        Args:
            name: Class name.
            cls: Class object.
            file_path: Source file path.
            repo_name: Repo directory name for settings namespace.

        Returns:
            SkillInfo with methods.
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
                params = [p for name, p in sig.parameters.items() if name != "self"]
                new_sig = sig.replace(parameters=params)
                sig_str = f"{method_name}{new_sig}"
            except ValueError:
                sig_str = f"{method_name}(...)"

            # Get docstring
            docstring = inspect.getdoc(method)

            methods.append(
                SkillMethod(
                    name=method_name,
                    signature=sig_str,
                    docstring=docstring,
                    callable=method,
                )
            )

        # Create instance, injecting settings_manager if the constructor accepts it
        instance = self._instantiate_skill(name, cls)

        # Check for class-level SETTINGS_SCHEMA as well
        class_schema = getattr(cls, "SETTINGS_SCHEMA", None)

        return SkillInfo(
            name=name,
            class_obj=cls,
            methods=methods,
            module_path=file_path,
            instance=instance,
            settings_schema=class_schema,
            repo_name=repo_name,
        )

    def _accepts_settings_manager(self, cls: type) -> bool:
        """Check if a class __init__ accepts a settings_manager parameter."""
        try:
            sig = inspect.signature(cls.__init__)
            return "settings_manager" in sig.parameters
        except (ValueError, TypeError):
            return False

    def _instantiate_skill(self, name: str, cls: type) -> Optional[Any]:
        """Create a skill instance, injecting settings_manager if accepted.

        Args:
            name: Skill class name (for logging).
            cls: The skill class to instantiate.

        Returns:
            Skill instance or None on failure.
        """
        try:
            if self._settings_manager and self._accepts_settings_manager(cls):
                return cls(settings_manager=self._settings_manager)
            return cls()
        except Exception as e:
            logger.warning(f"Failed to instantiate {name}: {e}")
            return None

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
                self._instances[skill_name] = self._instantiate_skill(
                    skill_name, skill.class_obj,
                )
        return self._instances.get(skill_name)

    @property
    def failures(self) -> List[SkillLoadFailure]:
        """Get the list of skill load failures from the last load_all()."""
        return list(self._failures)

    def get_all_skills(self) -> List[SkillInfo]:
        """Get all loaded skills."""
        return list(self._skills.values())

    def register_skill_settings(self) -> int:
        """Register discovered SETTINGS_SCHEMA with the SettingsManager.

        Iterates over loaded skills and registers any that have a
        ``settings_schema``. The namespace is ``skills.<repo_name>``,
        displayed on the "Skills" tab.

        Returns:
            Number of skill namespaces registered.
        """
        if not self._settings_manager:
            return 0

        registered = 0
        # Track which repo_names we've already registered (one namespace per repo)
        seen_repos: set[str] = set()

        for skill in self._skills.values():
            if not skill.settings_schema:
                continue

            repo = skill.repo_name or skill.name.lower()
            if repo in seen_repos:
                continue
            seen_repos.add(repo)

            namespace = f"skills.{repo}"
            if self._settings_manager.is_registered(namespace):
                logger.debug(
                    "Skill namespace '%s' already registered, skipping",
                    namespace,
                )
                continue

            # Derive a human-friendly display name from the repo name
            display_name = repo.replace("_", " ").replace("-", " ").title()
            # Strip trailing " Skill" to avoid "Weather Skill Skill" in UI
            if display_name.endswith(" Skill"):
                display_name = display_name[: -len(" Skill")]

            self._settings_manager.register(
                namespace=namespace,
                display_name=display_name,
                schema=skill.settings_schema,
                order=200,  # After core (10) and voice (20)
                tab="Skills",
            )
            logger.info(
                "Registered skill settings: %s (%d fields)",
                namespace,
                len(skill.settings_schema),
            )
            registered += 1

        return registered

    def get_registration_data(self) -> List[Dict[str, Any]]:
        """Get data for registering all skills with Hub.

        Returns:
            List of skill method dictionaries ready for API
        """
        data = []
        for skill in self._skills.values():
            data.extend(skill.get_registration_data())
        return data

    def call_method(self, skill_name: str, method_name: str, *args, **kwargs) -> Any:
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

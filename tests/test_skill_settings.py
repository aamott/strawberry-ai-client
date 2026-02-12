"""Tests for skill settings discovery, registration, and injection."""

import tempfile
from pathlib import Path

from strawberry.shared.settings import SettingsManager  # noqa: I001
from strawberry.skills.loader import SkillLoader

# ── Fixtures / helpers ──────────────────────────────────────────────


SKILL_WITH_SCHEMA = '''
from strawberry.shared.settings.schema import FieldType, SettingField

SETTINGS_SCHEMA = [
    SettingField(
        key="api_key",
        label="API Key",
        type=FieldType.PASSWORD,
        secret=True,
        description="Test API key",
        env_key="TEST_API_KEY",
    ),
    SettingField(
        key="mode",
        label="Mode",
        type=FieldType.SELECT,
        options=["fast", "slow"],
        default="fast",
    ),
]


class ConfiguredSkill:
    """Skill that accepts settings_manager."""

    def __init__(self, settings_manager=None):
        self._sm = settings_manager

    def get_mode(self) -> str:
        """Return configured mode."""
        if self._sm:
            return self._sm.get("skills.test_repo", "mode", "fast")
        return "fast"

    def has_settings(self) -> bool:
        """Check if settings_manager was injected."""
        return self._sm is not None
'''.lstrip()

SKILL_WITHOUT_SCHEMA = '''
class PlainSkill:
    """Skill with no settings schema."""

    def ping(self) -> str:
        """Return pong."""
        return "pong"
'''.lstrip()

SKILL_WITH_CLASS_SCHEMA = '''
from strawberry.shared.settings.schema import FieldType, SettingField


class ClassSchemaSkill:
    """Skill with SETTINGS_SCHEMA on the class itself."""

    SETTINGS_SCHEMA = [
        SettingField(
            key="color",
            label="Color",
            type=FieldType.TEXT,
            default="blue",
        ),
    ]

    def get_color(self) -> str:
        return "blue"
'''.lstrip()


def _make_settings_manager(tmpdir: str) -> SettingsManager:
    """Create a SettingsManager backed by a temp config dir."""
    config_dir = Path(tmpdir) / "config"
    config_dir.mkdir()
    return SettingsManager(config_dir=config_dir, auto_save=False)


# ── Discovery tests ─────────────────────────────────────────────────


def test_module_level_schema_discovered() -> None:
    """SkillLoader discovers SETTINGS_SCHEMA on the module."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir) / "skills"
        repo = skills_dir / "test_repo"
        repo.mkdir(parents=True)
        (repo / "skill.py").write_text(SKILL_WITH_SCHEMA)

        loader = SkillLoader(skills_dir)
        skills = loader.load_all()

        configured = [s for s in skills if s.name == "ConfiguredSkill"]
        assert len(configured) == 1
        skill = configured[0]
        assert skill.settings_schema is not None
        assert len(skill.settings_schema) == 2
        keys = {f.key for f in skill.settings_schema}
        assert keys == {"api_key", "mode"}


def test_no_schema_means_none() -> None:
    """Skills without SETTINGS_SCHEMA have settings_schema=None."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir) / "skills"
        repo = skills_dir / "plain_repo"
        repo.mkdir(parents=True)
        (repo / "skill.py").write_text(SKILL_WITHOUT_SCHEMA)

        loader = SkillLoader(skills_dir)
        skills = loader.load_all()

        plain = [s for s in skills if s.name == "PlainSkill"]
        assert len(plain) == 1
        assert plain[0].settings_schema is None


def test_class_level_schema_discovered() -> None:
    """SETTINGS_SCHEMA on the class itself is detected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir) / "skills"
        repo = skills_dir / "class_schema_repo"
        repo.mkdir(parents=True)
        (repo / "skill.py").write_text(SKILL_WITH_CLASS_SCHEMA)

        loader = SkillLoader(skills_dir)
        skills = loader.load_all()

        cs = [s for s in skills if s.name == "ClassSchemaSkill"]
        assert len(cs) == 1
        assert cs[0].settings_schema is not None
        assert cs[0].settings_schema[0].key == "color"


# ── Registration tests ───────────────────────────────────────────────


def test_register_skill_settings_with_manager() -> None:
    """register_skill_settings() creates namespace in SettingsManager."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sm = _make_settings_manager(tmpdir)

        skills_dir = Path(tmpdir) / "skills"
        repo = skills_dir / "test_repo"
        repo.mkdir(parents=True)
        (repo / "skill.py").write_text(SKILL_WITH_SCHEMA)

        loader = SkillLoader(skills_dir, settings_manager=sm)
        loader.load_all()
        count = loader.register_skill_settings()

        assert count == 1
        assert sm.is_registered("skills.test_repo")

        # Verify the schema was registered correctly
        schema = sm.get_schema("skills.test_repo")
        keys = {f.key for f in schema}
        assert "api_key" in keys
        assert "mode" in keys


def test_register_no_schema_means_no_namespace() -> None:
    """Skills without schema don't get a namespace registered."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sm = _make_settings_manager(tmpdir)

        skills_dir = Path(tmpdir) / "skills"
        repo = skills_dir / "plain_repo"
        repo.mkdir(parents=True)
        (repo / "skill.py").write_text(SKILL_WITHOUT_SCHEMA)

        loader = SkillLoader(skills_dir, settings_manager=sm)
        loader.load_all()
        count = loader.register_skill_settings()

        assert count == 0
        assert not sm.is_registered("skills.plain_repo")


def test_display_name_strips_skill_suffix() -> None:
    """Namespace display name strips trailing ' Skill'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sm = _make_settings_manager(tmpdir)

        skills_dir = Path(tmpdir) / "skills"
        repo = skills_dir / "weather_skill"
        repo.mkdir(parents=True)
        (repo / "skill.py").write_text(SKILL_WITH_SCHEMA)

        loader = SkillLoader(skills_dir, settings_manager=sm)
        loader.load_all()
        loader.register_skill_settings()

        ns = sm.get_namespace("skills.weather_skill")
        assert ns is not None
        # "Weather Skill" -> "Weather" (suffix stripped)
        assert ns.display_name == "Weather"


def test_tab_is_skills() -> None:
    """Skill settings are registered under the 'Skills' tab."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sm = _make_settings_manager(tmpdir)

        skills_dir = Path(tmpdir) / "skills"
        repo = skills_dir / "my_tool"
        repo.mkdir(parents=True)
        (repo / "skill.py").write_text(SKILL_WITH_SCHEMA)

        loader = SkillLoader(skills_dir, settings_manager=sm)
        loader.load_all()
        loader.register_skill_settings()

        ns = sm.get_namespace("skills.my_tool")
        assert ns is not None
        assert ns.tab == "Skills"


# ── Constructor injection tests ──────────────────────────────────────


def test_settings_manager_injected_into_constructor() -> None:
    """Skills that accept settings_manager get it injected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sm = _make_settings_manager(tmpdir)

        skills_dir = Path(tmpdir) / "skills"
        repo = skills_dir / "test_repo"
        repo.mkdir(parents=True)
        (repo / "skill.py").write_text(SKILL_WITH_SCHEMA)

        loader = SkillLoader(skills_dir, settings_manager=sm)
        skills = loader.load_all()

        configured = [s for s in skills if s.name == "ConfiguredSkill"]
        assert len(configured) == 1
        instance = configured[0].instance
        assert instance is not None
        assert instance.has_settings() is True


def test_plain_skill_instantiated_without_settings() -> None:
    """Skills without settings_manager param are instantiated normally."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sm = _make_settings_manager(tmpdir)

        skills_dir = Path(tmpdir) / "skills"
        repo = skills_dir / "plain_repo"
        repo.mkdir(parents=True)
        (repo / "skill.py").write_text(SKILL_WITHOUT_SCHEMA)

        loader = SkillLoader(skills_dir, settings_manager=sm)
        skills = loader.load_all()

        plain = [s for s in skills if s.name == "PlainSkill"]
        assert len(plain) == 1
        assert plain[0].instance is not None
        assert plain[0].instance.ping() == "pong"


# ── Value access tests ───────────────────────────────────────────────


def test_skill_reads_default_from_settings() -> None:
    """Skill can read its default setting value via SettingsManager."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sm = _make_settings_manager(tmpdir)

        skills_dir = Path(tmpdir) / "skills"
        repo = skills_dir / "test_repo"
        repo.mkdir(parents=True)
        (repo / "skill.py").write_text(SKILL_WITH_SCHEMA)

        loader = SkillLoader(skills_dir, settings_manager=sm)
        loader.load_all()
        loader.register_skill_settings()

        # Default value for "mode" is "fast"
        val = sm.get("skills.test_repo", "mode")
        assert val == "fast"


def test_skill_reads_updated_value() -> None:
    """Skill sees updated values after settings.set()."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sm = _make_settings_manager(tmpdir)

        skills_dir = Path(tmpdir) / "skills"
        repo = skills_dir / "test_repo"
        repo.mkdir(parents=True)
        (repo / "skill.py").write_text(SKILL_WITH_SCHEMA)

        loader = SkillLoader(skills_dir, settings_manager=sm)
        loader.load_all()
        loader.register_skill_settings()

        sm.set("skills.test_repo", "mode", "slow")
        val = sm.get("skills.test_repo", "mode")
        assert val == "slow"

        # The skill instance should also see the update
        instance = loader.get_instance("ConfiguredSkill")
        assert instance is not None
        assert instance.get_mode() == "slow"


def test_repo_name_stored_on_skill_info() -> None:
    """SkillInfo.repo_name is set to the repo directory name."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir) / "skills"
        repo = skills_dir / "my_custom_repo"
        repo.mkdir(parents=True)
        (repo / "skill.py").write_text(SKILL_WITHOUT_SCHEMA)

        loader = SkillLoader(skills_dir)
        skills = loader.load_all()

        assert len(skills) == 1
        assert skills[0].repo_name == "my_custom_repo"

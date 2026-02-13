"""Tests for the skill store — catalog, installer, and CLI."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from strawberry.skills.store.catalog import SkillCatalog
from strawberry.skills.store.cli import run_store_cli
from strawberry.skills.store.installer import SkillInstaller
from strawberry.skills.store.models import CatalogEntry

# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def tmp_catalog(tmp_path: Path) -> Path:
    """Create a temporary catalog YAML file."""
    catalog_data = {
        "skills": [
            {
                "name": "test_weather",
                "git_url": "",  # Will be set per-test
                "description": "Weather forecasts via API",
                "author": "tester",
                "tags": ["weather", "forecast", "api"],
                "version": "main",
                "requires": ["requests>=2.28"],
            },
            {
                "name": "test_calculator",
                "git_url": "",
                "description": "Basic math operations",
                "author": "tester",
                "tags": ["math", "calculator", "compute"],
                "version": "main",
                "requires": [],
            },
        ],
    }
    path = tmp_path / "test_catalog.yaml"
    with open(path, "w") as f:
        yaml.dump(catalog_data, f)
    return path


@pytest.fixture
def local_git_repo(tmp_path: Path) -> Path:
    """Create a minimal local git repo that looks like a skill."""
    repo_dir = tmp_path / "test_skill_repo"
    repo_dir.mkdir()

    # Create a minimal skill.py
    (repo_dir / "skill.py").write_text(
        'class TestRepoSkill:\n'
        '    """A test skill."""\n'
        '    def hello(self) -> str:\n'
        '        return "hello"\n',
        encoding="utf-8",
    )

    # Create requirements.txt
    (repo_dir / "requirements.txt").write_text(
        "# Test deps\nrequests>=2.28\n",
        encoding="utf-8",
    )

    # Init git repo
    subprocess.run(
        ["git", "init"], cwd=str(repo_dir),
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "add", "-A"], cwd=str(repo_dir),
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(repo_dir),
        capture_output=True, check=True,
        env={
            **__import__("os").environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@test.com",
        },
    )
    return repo_dir


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    """Create a temporary skills directory."""
    d = tmp_path / "skills"
    d.mkdir()
    return d


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """Create a temporary config directory."""
    d = tmp_path / "config"
    d.mkdir()
    return d


# ── CatalogEntry model tests ───────────────────────────────────────


class TestCatalogEntry:
    """Tests for CatalogEntry.matches()."""

    def test_matches_name(self):
        entry = CatalogEntry(name="weather_skill", git_url="x")
        assert entry.matches("weather")

    def test_matches_description(self):
        entry = CatalogEntry(
            name="foo", git_url="x", description="Get the forecast",
        )
        assert entry.matches("forecast")

    def test_matches_tags(self):
        entry = CatalogEntry(
            name="foo", git_url="x", tags=["temperature", "api"],
        )
        assert entry.matches("temperature")

    def test_matches_author(self):
        entry = CatalogEntry(name="foo", git_url="x", author="alice")
        assert entry.matches("alice")

    def test_matches_all_terms_required(self):
        entry = CatalogEntry(
            name="weather_skill", git_url="x",
            description="forecasts", tags=["api"],
        )
        # Both terms must match
        assert entry.matches("weather api")
        assert not entry.matches("weather calculator")

    def test_matches_empty_query(self):
        entry = CatalogEntry(name="foo", git_url="x")
        assert entry.matches("")

    def test_matches_case_insensitive(self):
        entry = CatalogEntry(name="WeatherSkill", git_url="x")
        assert entry.matches("weatherskill")
        assert entry.matches("WEATHERSKILL")


# ── SkillCatalog tests ──────────────────────────────────────────────


class TestSkillCatalog:
    """Tests for SkillCatalog loading and searching."""

    def test_load_catalog(self, tmp_catalog: Path):
        catalog = SkillCatalog(tmp_catalog)
        count = catalog.load()
        assert count == 2

    def test_list_all(self, tmp_catalog: Path):
        catalog = SkillCatalog(tmp_catalog)
        entries = catalog.list_all()
        assert len(entries) == 2
        names = {e.name for e in entries}
        assert names == {"test_weather", "test_calculator"}

    def test_search_by_keyword(self, tmp_catalog: Path):
        catalog = SkillCatalog(tmp_catalog)
        results = catalog.search("weather")
        assert len(results) == 1
        assert results[0].name == "test_weather"

    def test_search_no_results(self, tmp_catalog: Path):
        catalog = SkillCatalog(tmp_catalog)
        results = catalog.search("nonexistent_xyz")
        assert len(results) == 0

    def test_search_empty_returns_all(self, tmp_catalog: Path):
        catalog = SkillCatalog(tmp_catalog)
        results = catalog.search("")
        assert len(results) == 2

    def test_get_by_name(self, tmp_catalog: Path):
        catalog = SkillCatalog(tmp_catalog)
        entry = catalog.get("test_weather")
        assert entry is not None
        assert entry.name == "test_weather"

    def test_get_missing(self, tmp_catalog: Path):
        catalog = SkillCatalog(tmp_catalog)
        assert catalog.get("nonexistent") is None

    def test_load_missing_file(self, tmp_path: Path):
        catalog = SkillCatalog(tmp_path / "nope.yaml")
        with pytest.raises(FileNotFoundError):
            catalog.load()

    def test_len(self, tmp_catalog: Path):
        catalog = SkillCatalog(tmp_catalog)
        assert len(catalog) == 2

    def test_default_catalog_loads(self):
        """The shipped catalog file should load without errors."""
        catalog = SkillCatalog()
        count = catalog.load()
        assert count >= 1


# ── SkillInstaller tests ───────────────────────────────────────────


class TestSkillInstaller:
    """Tests for SkillInstaller install/uninstall/update."""

    def test_install_from_local_repo(
        self, local_git_repo: Path, skills_dir: Path, config_dir: Path,
    ):
        installer = SkillInstaller(skills_dir, config_dir)
        record = installer.install(str(local_git_repo), install_deps=False)

        assert record.name == "test_skill_repo"
        assert (skills_dir / "test_skill_repo" / "skill.py").exists()
        assert record.from_catalog is False

    def test_install_creates_record(
        self, local_git_repo: Path, skills_dir: Path, config_dir: Path,
    ):
        installer = SkillInstaller(skills_dir, config_dir)
        installer.install(str(local_git_repo), install_deps=False)

        record = installer.get_record("test_skill_repo")
        assert record is not None
        assert record.source_url == str(local_git_repo)

    def test_install_duplicate_raises(
        self, local_git_repo: Path, skills_dir: Path, config_dir: Path,
    ):
        installer = SkillInstaller(skills_dir, config_dir)
        installer.install(str(local_git_repo), install_deps=False)

        with pytest.raises(FileExistsError):
            installer.install(str(local_git_repo), install_deps=False)

    def test_install_force_overwrites(
        self, local_git_repo: Path, skills_dir: Path, config_dir: Path,
    ):
        installer = SkillInstaller(skills_dir, config_dir)
        installer.install(str(local_git_repo), install_deps=False)

        # Force reinstall should succeed
        record = installer.install(
            str(local_git_repo), install_deps=False, force=True,
        )
        assert record.name == "test_skill_repo"

    def test_uninstall(
        self, local_git_repo: Path, skills_dir: Path, config_dir: Path,
    ):
        installer = SkillInstaller(skills_dir, config_dir)
        installer.install(str(local_git_repo), install_deps=False)

        removed = installer.uninstall("test_skill_repo")
        assert removed is True
        assert not (skills_dir / "test_skill_repo").exists()
        assert installer.get_record("test_skill_repo") is None

    def test_uninstall_nonexistent(
        self, skills_dir: Path, config_dir: Path,
    ):
        installer = SkillInstaller(skills_dir, config_dir)
        assert installer.uninstall("nonexistent") is False

    def test_list_installed(
        self, local_git_repo: Path, skills_dir: Path, config_dir: Path,
    ):
        installer = SkillInstaller(skills_dir, config_dir)
        installer.install(str(local_git_repo), install_deps=False)

        installed = installer.list_installed()
        assert len(installed) == 1
        assert installed[0].name == "test_skill_repo"

    def test_list_installed_empty(
        self, skills_dir: Path, config_dir: Path,
    ):
        installer = SkillInstaller(skills_dir, config_dir)
        assert installer.list_installed() == []

    def test_detect_deps_from_requirements_txt(
        self, local_git_repo: Path, skills_dir: Path, config_dir: Path,
    ):
        installer = SkillInstaller(skills_dir, config_dir)
        # Install without deps to check detection
        installer.install(str(local_git_repo), install_deps=False)

        deps = installer._detect_deps(skills_dir / "test_skill_repo")
        assert "requests>=2.28" in deps

    def test_update_pulls_latest(
        self, local_git_repo: Path, skills_dir: Path, config_dir: Path,
    ):
        installer = SkillInstaller(skills_dir, config_dir)
        installer.install(str(local_git_repo), install_deps=False)

        # Make a new commit in the source repo
        readme = local_git_repo / "README.md"
        readme.write_text("# Updated", encoding="utf-8")
        subprocess.run(
            ["git", "add", "-A"], cwd=str(local_git_repo),
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "update"],
            cwd=str(local_git_repo),
            capture_output=True, check=True,
            env={
                **__import__("os").environ,
                "GIT_AUTHOR_NAME": "test",
                "GIT_AUTHOR_EMAIL": "test@test.com",
                "GIT_COMMITTER_NAME": "test",
                "GIT_COMMITTER_EMAIL": "test@test.com",
            },
        )

        # Update should pull the new commit
        updated = installer.update(
            "test_skill_repo", install_deps=False,
        )
        assert updated is not None
        # The README should now exist in the installed copy
        assert (
            skills_dir / "test_skill_repo" / "README.md"
        ).exists()


# ── Name extraction tests ──────────────────────────────────────────


class TestNameFromUrl:
    """Tests for SkillInstaller._name_from_url()."""

    def test_github_https(self):
        name = SkillInstaller._name_from_url(
            "https://github.com/user/weather_skill.git",
        )
        assert name == "weather_skill"

    def test_github_no_git_suffix(self):
        name = SkillInstaller._name_from_url(
            "https://github.com/user/weather-skill",
        )
        assert name == "weather_skill"

    def test_trailing_slash(self):
        name = SkillInstaller._name_from_url(
            "https://github.com/user/my-skill/",
        )
        assert name == "my_skill"

    def test_local_path(self):
        name = SkillInstaller._name_from_url("/tmp/my-cool-skill")
        assert name == "my_cool_skill"


# ── Dependency parsing tests ───────────────────────────────────────


class TestDependencyParsing:
    """Tests for requirements.txt and pyproject.toml parsing."""

    def test_parse_requirements_txt(self, tmp_path: Path):
        req = tmp_path / "requirements.txt"
        req.write_text(
            "# Comment\nrequests>=2.28\n\nnumpy\n-e .\n",
            encoding="utf-8",
        )
        deps = SkillInstaller._parse_requirements_txt(req)
        assert deps == ["requests>=2.28", "numpy"]

    def test_parse_requirements_txt_empty(self, tmp_path: Path):
        req = tmp_path / "requirements.txt"
        req.write_text("# Only comments\n", encoding="utf-8")
        deps = SkillInstaller._parse_requirements_txt(req)
        assert deps == []

    def test_parse_pyproject_deps(self, tmp_path: Path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "test"\n'
            'dependencies = ["requests>=2.28", "pyyaml"]\n',
            encoding="utf-8",
        )
        deps = SkillInstaller._parse_pyproject_deps(pyproject)
        assert deps == ["requests>=2.28", "pyyaml"]


# ── CLI tests ───────────────────────────────────────────────────────


class TestStoreCLI:
    """Tests for the store CLI subcommands."""

    def test_cli_list(self, capsys):
        """CLI list should show catalog entries."""
        run_store_cli(["list"])
        output = capsys.readouterr().out
        assert "weather_skill" in output

    def test_cli_search(self, capsys):
        """CLI search should filter results."""
        run_store_cli(["search", "weather"])
        output = capsys.readouterr().out
        assert "weather_skill" in output
        assert "internet_skill" not in output

    def test_cli_search_no_results(self, capsys):
        """CLI search with no matches should say so."""
        run_store_cli(["search", "zzz_nonexistent_zzz"])
        output = capsys.readouterr().out
        assert "No skills found" in output

    def test_cli_installed_empty(self, capsys, tmp_path: Path):
        """CLI installed with no installs should say so."""
        with patch(
            "strawberry.skills.store.cli._resolve_paths",
            return_value=(
                tmp_path / "skills",
                tmp_path / "config",
                Path("python"),
            ),
        ):
            (tmp_path / "skills").mkdir()
            (tmp_path / "config").mkdir()
            run_store_cli(["installed"])
            output = capsys.readouterr().out
            assert "No skills installed" in output

    def test_cli_help(self, capsys):
        """CLI with no subcommand should show help."""
        run_store_cli([])
        output = capsys.readouterr().out
        assert "Strawberry Skill Store" in output

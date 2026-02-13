"""Tests for the GUI theme loader."""

import textwrap
from pathlib import Path

import pytest

from strawberry.ui.gui_v2.themes.base import Theme
from strawberry.ui.gui_v2.themes.loader import (
    discover_themes,
    ensure_builtin_themes,
    get_theme_names,
    load_theme_from_yaml,
)


@pytest.fixture()
def themes_dir(tmp_path: Path) -> Path:
    """Create a temporary themes directory."""
    d = tmp_path / "themes"
    d.mkdir()
    return d


def _write_theme(path: Path, name: str = "test_theme") -> Path:
    """Write a minimal valid theme YAML file.

    Args:
        path: Directory to write into.
        name: Theme name.

    Returns:
        Path to the created file.
    """
    content = textwrap.dedent(f"""\
        name: {name}
        bg_primary: "#111111"
        bg_secondary: "#222222"
        bg_tertiary: "#333333"
        bg_input: "#111111"
        bg_hover: "#222222"
        bg_selected: "#333333"
        text_primary: "#ffffff"
        text_secondary: "#aaaaaa"
        text_muted: "#666666"
        text_link: "#0000ff"
        accent_primary: "#ff0000"
        accent_secondary: "#00ff00"
        success: "#00ff00"
        warning: "#ffff00"
        error: "#ff0000"
        info: "#0000ff"
        border: "#333333"
        border_light: "#444444"
        message_user_bg: "#222222"
        message_assistant_bg: "#111111"
        tool_call_bg: "#222222"
        sidebar_bg: "#111111"
        titlebar_bg: "#111111"
        statusbar_bg: "#111111"
    """)
    filepath = path / f"{name}.yaml"
    filepath.write_text(content)
    return filepath


class TestLoadThemeFromYaml:
    """Tests for load_theme_from_yaml."""

    def test_valid_theme(self, themes_dir: Path) -> None:
        """Valid YAML produces a Theme instance."""
        path = _write_theme(themes_dir, "my_theme")
        theme = load_theme_from_yaml(path)
        assert theme is not None
        assert isinstance(theme, Theme)
        assert theme.name == "my_theme"
        assert theme.bg_primary == "#111111"

    def test_missing_required_field(self, themes_dir: Path) -> None:
        """Missing required field returns None."""
        path = themes_dir / "bad.yaml"
        path.write_text("name: bad\nbg_primary: '#111'\n")
        theme = load_theme_from_yaml(path)
        assert theme is None

    def test_invalid_yaml(self, themes_dir: Path) -> None:
        """Malformed YAML returns None."""
        path = themes_dir / "broken.yaml"
        path.write_text("{{not valid yaml")
        theme = load_theme_from_yaml(path)
        assert theme is None

    def test_name_defaults_to_stem(self, themes_dir: Path) -> None:
        """If 'name' is missing from YAML, use filename stem."""
        path = _write_theme(themes_dir, "auto_name")
        # Remove the name line
        text = path.read_text().replace("name: auto_name\n", "")
        path.write_text(text)
        theme = load_theme_from_yaml(path)
        assert theme is not None
        assert theme.name == "auto_name"


class TestDiscoverThemes:
    """Tests for discover_themes."""

    def test_discovers_yaml_files(self, themes_dir: Path) -> None:
        """Discovers all .yaml files in directory."""
        _write_theme(themes_dir, "alpha")
        _write_theme(themes_dir, "beta")
        themes = discover_themes(themes_dir)
        assert "alpha" in themes
        assert "beta" in themes
        assert len(themes) == 2

    def test_skips_underscore_files(self, themes_dir: Path) -> None:
        """Files starting with _ are skipped."""
        _write_theme(themes_dir, "visible")
        # Write a _template file
        _write_theme(themes_dir, "_template")
        # Rename to start with _
        (themes_dir / "_template.yaml").rename(themes_dir / "_hidden.yaml")
        themes = discover_themes(themes_dir)
        assert "visible" in themes
        assert "_hidden" not in themes

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        """Nonexistent directory returns empty dict."""
        themes = discover_themes(tmp_path / "nope")
        assert themes == {}

    def test_skips_invalid_files(self, themes_dir: Path) -> None:
        """Invalid theme files are skipped without crashing."""
        _write_theme(themes_dir, "good")
        (themes_dir / "bad.yaml").write_text("name: bad\n")
        themes = discover_themes(themes_dir)
        assert "good" in themes
        assert "bad" not in themes


class TestEnsureBuiltinThemes:
    """Tests for ensure_builtin_themes."""

    def test_copies_builtins(self, themes_dir: Path) -> None:
        """Built-in themes are copied to empty directory."""
        ensure_builtin_themes(themes_dir)
        files = list(themes_dir.glob("*.yaml"))
        # Should have at least dark.yaml, light.yaml, _template.yaml
        names = {f.name for f in files}
        assert "dark.yaml" in names
        assert "light.yaml" in names
        assert "_template.yaml" in names

    def test_does_not_overwrite(self, themes_dir: Path) -> None:
        """Existing files are not overwritten."""
        custom = themes_dir / "dark.yaml"
        custom.write_text("custom content")
        ensure_builtin_themes(themes_dir)
        assert custom.read_text() == "custom content"

    def test_creates_directory(self, tmp_path: Path) -> None:
        """Creates the themes directory if it doesn't exist."""
        new_dir = tmp_path / "new" / "themes"
        ensure_builtin_themes(new_dir)
        assert new_dir.is_dir()


class TestGetThemeNames:
    """Tests for get_theme_names."""

    def test_returns_sorted_names(self, themes_dir: Path) -> None:
        """Returns sorted list of theme names."""
        _write_theme(themes_dir, "zebra")
        _write_theme(themes_dir, "alpha")
        names = get_theme_names(themes_dir)
        assert names == ["alpha", "zebra"]

    def test_excludes_underscored(self, themes_dir: Path) -> None:
        """Template files are excluded."""
        _write_theme(themes_dir, "real")
        (themes_dir / "_template.yaml").write_text("ignore me")
        names = get_theme_names(themes_dir)
        assert names == ["real"]

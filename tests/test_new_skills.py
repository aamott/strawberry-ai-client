"""Tests for new skills: internet, media control, and system control."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from strawberry.skills.loader import SkillLoader
from strawberry.skills.service import SkillService


@pytest.fixture
def skills_dir():
    """Create a temporary skills directory with new skills."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Copy the new skill repos
        skills_base = Path(__file__).parent.parent / "skills"

        repo_names = [
            "internet_skill",
            "media_control_skill",
            "system_control_skill",
        ]

        for repo_name in repo_names:
            repo_dir = Path(tmpdir) / repo_name
            repo_dir.mkdir(parents=True, exist_ok=True)
            (repo_dir / "skill.py").write_text(
                (skills_base / repo_name / "skill.py").read_text()
            )

        yield Path(tmpdir)


@pytest.fixture
def loader(skills_dir):
    """Create a skill loader with new skills."""
    return SkillLoader(skills_dir)


class TestInternetSkills:
    """Tests for InternetSearchSkill and WebBrowserSkill."""

    def test_internet_skills_loaded(self, loader):
        """Test that internet skills are loaded."""
        skills = loader.load_all()
        skill_names = [s.name for s in skills]

        assert "InternetSearchSkill" in skill_names
        assert "WebBrowserSkill" in skill_names

    def test_search_web_method(self, loader):
        """Test search_web method."""
        loader.load_all()

        # Test Python search
        results = loader.call_method("InternetSearchSkill", "search_web", "python programming")
        assert isinstance(results, list)
        assert len(results) > 0
        assert any("Python" in result["title"] for result in results)

        # Test Schrödinger equation search
        schrodinger_results = loader.call_method(
            "InternetSearchSkill",
            "search_web",
            "schrödinger equation formula",
        )
        assert len(schrodinger_results) > 0
        assert any("Schrödinger" in result["title"] for result in schrodinger_results)
        assert any("Wikipedia" in result["title"] for result in schrodinger_results)

    def test_open_website_method(self, loader):
        """Test open_website method."""
        loader.load_all()

        with patch('webbrowser.open') as mock_open:
            result = loader.call_method("InternetSearchSkill", "open_website", "https://example.com")
            assert "example.com" in result
            mock_open.assert_called_once()

    def test_get_website_info_method(self, loader):
        """Test get_website_info method."""
        loader.load_all()

        info = loader.call_method("InternetSearchSkill", "get_website_info", "https://example.com")
        assert "example.com" in info["url"]
        assert info["safe"]

    def test_web_browser_methods(self, loader):
        """Test web browser navigation methods."""
        loader.load_all()

        # Test all navigation methods
        assert "back" in loader.call_method("WebBrowserSkill", "navigate_back")
        assert "forward" in loader.call_method("WebBrowserSkill", "navigate_forward")
        assert "refreshed" in loader.call_method("WebBrowserSkill", "refresh_page")
        assert "closed" in loader.call_method("WebBrowserSkill", "close_browser")

    def test_extract_search_summary(self, loader):
        """Test extract_search_summary method."""
        loader.load_all()

        # Test Schrödinger equation formula summary
        summary = loader.call_method(
            "InternetSearchSkill",
            "extract_search_summary",
            "schrödinger equation formula",
        )
        assert "iħ∂ψ/∂t = Ĥψ" in summary
        assert "quantum mechanics" in summary

        # Test Python programming summary
        python_summary = loader.call_method(
            "InternetSearchSkill",
            "extract_search_summary",
            "python programming",
        )
        assert "high-level" in python_summary
        assert "programming language" in python_summary

        # Test unknown query
        unknown_summary = loader.call_method(
            "InternetSearchSkill",
            "extract_search_summary",
            "unknown topic xyz",
        )
        assert "unknown topic xyz" in unknown_summary


class TestMediaControlSkills:
    """Tests for MediaControlSkill and MusicLibrarySkill."""

    def test_media_control_skills_loaded(self, loader):
        """Test that media control skills are loaded."""
        skills = loader.load_all()
        skill_names = [s.name for s in skills]

        assert "MediaControlSkill" in skill_names
        assert "MusicLibrarySkill" in skill_names

    def test_media_playback_methods(self, loader):
        """Test media playback control methods."""
        loader.load_all()

        # Test all playback methods
        assert "play" in loader.call_method("MediaControlSkill", "play")
        assert "pause" in loader.call_method("MediaControlSkill", "pause")
        assert "stop" in loader.call_method("MediaControlSkill", "stop")
        assert "next" in loader.call_method("MediaControlSkill", "next_track")
        assert "previous" in loader.call_method("MediaControlSkill", "previous_track")

    def test_volume_control(self, loader):
        """Test volume control methods."""
        loader.load_all()

        # Test get volume
        volume = loader.call_method("MediaControlSkill", "get_volume")
        assert isinstance(volume, int)
        assert 0 <= volume <= 100

        # Test set volume
        result = loader.call_method("MediaControlSkill", "set_volume", 50)
        assert "50" in result

        # Test invalid volume
        with pytest.raises(ValueError, match="Volume must be between 0 and 100"):
            loader.call_method("MediaControlSkill", "set_volume", 150)

    def test_current_track(self, loader):
        """Test get_current_track method."""
        loader.load_all()

        track = loader.call_method("MediaControlSkill", "get_current_track")
        assert "title" in track
        assert "artist" in track
        assert "album" in track

    def test_music_library_methods(self, loader):
        """Test music library management methods."""
        loader.load_all()

        # Test search
        results = loader.call_method("MusicLibrarySkill", "search_songs", "relaxing")
        assert isinstance(results, list)
        assert len(results) > 0

        # Test playlist creation
        result = loader.call_method(
            "MusicLibrarySkill",
            "create_playlist",
            "My Playlist",
            ["Song 1", "Song 2"],
        )
        assert "My Playlist" in result
        assert "2" in result

        # Test play playlist
        result = loader.call_method("MusicLibrarySkill", "play_playlist", "My Playlist")
        assert "My Playlist" in result


class TestSystemControlSkills:
    """Tests for SystemControlSkill and DisplayControlSkill."""

    def test_system_control_skills_loaded(self, loader):
        """Test that system control skills are loaded."""
        skills = loader.load_all()
        skill_names = [s.name for s in skills]

        assert "SystemControlSkill" in skill_names
        assert "DisplayControlSkill" in skill_names

    def test_system_info(self, loader):
        """Test get_system_info method."""
        loader.load_all()

        info = loader.call_method("SystemControlSkill", "get_system_info")
        assert "os" in info
        assert "processor" in info
        assert "hostname" in info

    def test_system_volume_control(self, loader):
        """Test system volume control methods."""
        loader.load_all()

        # Test get volume
        volume = loader.call_method("SystemControlSkill", "get_system_volume")
        assert isinstance(volume, int)
        assert 0 <= volume <= 100

        # Test set volume
        result = loader.call_method("SystemControlSkill", "set_system_volume", 60)
        assert "60" in result

        # Test invalid volume
        with pytest.raises(ValueError, match="Volume must be between 0 and 100"):
            loader.call_method("SystemControlSkill", "set_system_volume", 150)

    def test_system_power_methods(self, loader):
        """Test system power management methods."""
        loader.load_all()

        # Test sleep
        result = loader.call_method("SystemControlSkill", "sleep_system")
        assert "sleep" in result.lower()

        # Test restart
        result = loader.call_method("SystemControlSkill", "restart_system")
        assert "restart" in result.lower()

        # Test shutdown
        result = loader.call_method("SystemControlSkill", "shutdown_system")
        assert "shutdown" in result.lower()

    def test_display_control(self, loader):
        """Test display control methods."""
        loader.load_all()

        # Test get brightness
        brightness = loader.call_method("DisplayControlSkill", "get_brightness")
        assert isinstance(brightness, int)
        assert 0 <= brightness <= 100

        # Test set brightness
        result = loader.call_method("DisplayControlSkill", "set_brightness", 80)
        assert "80" in result

        # Test invalid brightness
        with pytest.raises(ValueError, match="Brightness must be between 0 and 100"):
            loader.call_method("DisplayControlSkill", "set_brightness", 150)


class TestSkillIntegration:
    """Tests for skill integration with the service."""

    @pytest.fixture
    def service(self, skills_dir):
        """Create skill service with new skills."""
        return SkillService(skills_dir)

    def test_internet_skill_discovery(self, service):
        """Test discovering internet skills."""
        service.load_skills()

        # Test search for internet skills
        code = "results = device.search_skills('web')\nprint(results)"
        result = service.execute_code(code)

        assert result.success
        assert "InternetSearchSkill" in result.result

    def test_media_skill_execution(self, service):
        """Test executing media control skills."""
        service.load_skills()

        # Test playing media
        code = "result = device.MediaControlSkill.play()\nprint(result)"
        result = service.execute_code(code)

        assert result.success
        assert "play" in result.result.lower()

    def test_system_skill_execution(self, service):
        """Test executing system control skills."""
        service.load_skills()

        # Test getting system info
        code = "info = device.SystemControlSkill.get_system_info()\nprint(info)"
        result = service.execute_code(code)

        assert result.success
        assert "os" in result.result

    def test_complete_workflow(self, service):
        """Test complete workflow: search → describe → execute."""
        service.load_skills()

        # Step 1: Search for media skills
        code1 = "results = device.search_skills('media')\nprint(results)"
        result1 = service.execute_code(code1)
        assert result1.success
        assert "MediaControlSkill" in result1.result

        # Step 2: Get details about a specific method
        code2 = "info = device.describe_function('MediaControlSkill.play')\nprint(info)"
        result2 = service.execute_code(code2)
        assert result2.success
        assert "def play" in result2.result

        # Step 3: Execute the method
        code3 = "result = device.MediaControlSkill.play()\nprint(result)"
        result3 = service.execute_code(code3)
        assert result3.success
        assert "play" in result3.result.lower()

    def test_process_response_with_new_skills(self, service):
        """Test processing LLM response with new skill calls."""
        service.load_skills()

        # Test response with internet search
        response = (
            "Let me search the web:\n\n"
            "```python\n"
            'results = device.InternetSearchSkill.search_web("python programming")\n'
            "print(results)\n"
            "```"
        )

        processed, tool_calls = service.process_response(response)

        assert len(tool_calls) == 1
        assert tool_calls[0]["success"]
        # Now we get actual search results, not just the query string
        assert "Python.org" in processed  # Check for actual result content
        assert "W3Schools" in processed

        # Test response with media control
        response2 = (
            "Let me control the media:\n\n"
            "```python\n"
            "result = device.MediaControlSkill.play()\n"
            "print(result)\n"
            "```"
        )

        processed2, tool_calls2 = service.process_response(response2)

        assert len(tool_calls2) == 1
        assert tool_calls2[0]["success"]
        assert "play" in processed2.lower()

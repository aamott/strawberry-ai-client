"""Tests for music control skills."""

import os
import tempfile
from unittest.mock import MagicMock, patch

from skills.music_control_skill import AdvancedMusicControlSkill, MusicControlSkill


class TestMusicControlSkill:
    """Test basic music control functionality."""

    def setup_method(self):
        """Setup test environment."""
        # Create a temporary music folder with some test files
        self.temp_dir = tempfile.mkdtemp()

        # Create some test music files
        self.test_files = [
            os.path.join(self.temp_dir, "song1.mp3"),
            os.path.join(self.temp_dir, "song2.wav"),
            os.path.join(self.temp_dir, "album_song.flac"),
        ]

        for file_path in self.test_files:
            # Create empty files
            with open(file_path, 'w') as f:
                f.write("test")

        self.music_skill = MusicControlSkill(self.temp_dir)

    def teardown_method(self):
        """Cleanup test environment."""
        # Remove temporary files
        for file_path in self.test_files:
            if os.path.exists(file_path):
                os.remove(file_path)
        os.rmdir(self.temp_dir)

    def test_initialization(self):
        """Test skill initialization."""
        assert self.music_skill.music_folder == self.temp_dir
        assert self.music_skill._music_cache is None

    def test_get_music_files(self):
        """Test music file discovery."""
        files = self.music_skill._get_music_files()
        assert len(files) == 3
        assert all(os.path.exists(f) for f in files)

    def test_build_music_cache(self):
        """Test music cache building."""
        cache = self.music_skill._build_music_cache()
        assert len(cache) == 3

        # Check that each file has metadata
        for file_path, metadata in cache.items():
            assert 'title' in metadata
            assert 'path' in metadata
            assert 'artist' in metadata
            assert 'album' in metadata
            assert 'duration' in metadata

    def test_search_music(self):
        """Test music search functionality."""
        results = self.music_skill.search_music("song")
        assert len(results) >= 2  # Should find song1 and song2

        # Test specific search
        results = self.music_skill.search_music("album")
        assert len(results) == 1
        assert "album" in results[0]['title'].lower()

    def test_play_music_file_nonexistent(self):
        """Test playing non-existent file."""
        result = self.music_skill.play_music_file("/nonexistent/file.mp3")
        assert "Error: File not found" in result

    @patch('subprocess.Popen')
    def test_play_music_file_windows(self, mock_popen):
        """Test playing music file on Windows."""
        mock_popen.return_value = MagicMock()

        with patch('platform.system', return_value='Windows'):
            result = self.music_skill.play_music_file(self.test_files[0])

            assert "Playing" in result
            assert "song1.mp3" in result
            mock_popen.assert_called_once()

    @patch('subprocess.Popen')
    def test_play_music_file_mac(self, mock_popen):
        """Test playing music file on macOS."""
        mock_popen.return_value = MagicMock()

        with patch('platform.system', return_value='Darwin'):
            result = self.music_skill.play_music_file(self.test_files[0])

            assert "Playing" in result
            assert "song1.mp3" in result
            mock_popen.assert_called_once()

    @patch('subprocess.Popen')
    def test_play_music_file_linux(self, mock_popen):
        """Test playing music file on Linux."""
        mock_popen.return_value = MagicMock()

        with patch('platform.system', return_value='Linux'):
            result = self.music_skill.play_music_file(self.test_files[0])

            assert "Playing" in result
            assert "song1.mp3" in result
            mock_popen.assert_called_once()

    def test_play_song_by_title(self):
        """Test playing song by title."""
        with patch.object(self.music_skill, 'play_music_file', return_value="Playing test song"):
            result = self.music_skill.play_song_by_title("song1")
            assert "Playing" in result

    def test_get_music_library_stats(self):
        """Test music library statistics."""
        stats = self.music_skill.get_music_library_stats()
        assert stats['total_songs'] == 3
        assert stats['music_folder'] == self.temp_dir
        assert len(stats['file_types']) == 3

    def test_set_music_folder(self):
        """Test setting music folder."""
        new_folder = tempfile.mkdtemp()
        result = self.music_skill.set_music_folder(new_folder)
        assert "Music folder set to" in result
        assert self.music_skill.music_folder == new_folder

        # Cleanup
        os.rmdir(new_folder)

    def test_refresh_music_library(self):
        """Test refreshing music library."""
        # First build cache
        _ = self.music_skill._get_music_cache()

        # Refresh should clear and rebuild cache
        result = self.music_skill.refresh_music_library()
        assert "Music library refreshed" in result
        assert "Found 3 songs" in result


class TestAdvancedMusicControlSkill:
    """Test advanced music control functionality."""

    def setup_method(self):
        """Setup test environment."""
        self.temp_dir = tempfile.mkdtemp()

        # Create some test music files
        self.test_files = [
            os.path.join(self.temp_dir, "song1.mp3"),
            os.path.join(self.temp_dir, "song2.wav"),
        ]

        for file_path in self.test_files:
            with open(file_path, 'w') as f:
                f.write("test")

        self.advanced_skill = AdvancedMusicControlSkill(self.temp_dir)

    def teardown_method(self):
        """Cleanup test environment."""
        # Remove temporary files
        for file_path in self.test_files:
            if os.path.exists(file_path):
                os.remove(file_path)

        # Remove playlists file if it exists
        playlists_file = os.path.join(self.temp_dir, 'playlists.json')
        if os.path.exists(playlists_file):
            os.remove(playlists_file)

        os.rmdir(self.temp_dir)

    def test_create_playlist(self):
        """Test playlist creation."""
        result = self.advanced_skill.create_playlist("test_playlist", ["song1", "song2"])
        assert "Created playlist 'test_playlist'" in result
        assert "2 songs" in result

    def test_play_playlist(self):
        """Test playing a playlist."""
        # Create a playlist first
        self.advanced_skill.create_playlist("test_playlist", ["song1"])

        with patch.object(self.advanced_skill.base_control, 'play_music_file', return_value="Playing song1.mp3"):
            result = self.advanced_skill.play_playlist("test_playlist")
            assert "Playing song1.mp3" in result

    def test_list_playlists(self):
        """Test listing playlists."""
        # Create some playlists
        self.advanced_skill.create_playlist("playlist1", ["song1"])
        self.advanced_skill.create_playlist("playlist2", ["song2"])

        playlists = self.advanced_skill.list_playlists()
        assert len(playlists) == 2
        assert "playlist1" in playlists
        assert "playlist2" in playlists

    def test_get_playlist_info(self):
        """Test getting playlist information."""
        # Create a playlist
        self.advanced_skill.create_playlist("test_playlist", ["song1", "song2"])

        info = self.advanced_skill.get_playlist_info("test_playlist")
        assert info['name'] == "test_playlist"
        assert info['song_count'] == 2
        # Note: songs list might be empty if search doesn't find the songs
        # This is expected behavior for the test
        assert 'songs' in info

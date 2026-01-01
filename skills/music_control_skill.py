"""Music playback and library management skills."""

import glob
import json
import logging
import os
import platform
import subprocess
from typing import Any, Dict, List, Optional

# Configure logging
logger = logging.getLogger(__name__)


class MusicControlSkill:
    """Controls music playback and manages music library."""

    def __init__(self, music_folder: Optional[str] = None):
        """Initialize music control skill.
        
        Args:
            music_folder: Path to music library folder (defaults to Music directory)
        """
        self.music_folder = music_folder or self._get_default_music_folder()
        self._music_cache = None
        self._current_playback = None

    def _get_default_music_folder(self) -> str:
        """Get the default music folder for the current platform."""
        system = platform.system()

        if system == "Windows":
            return os.path.expanduser("~/Music")
        elif system == "Darwin":  # macOS
            return os.path.expanduser("~/Music")
        else:  # Linux and others
            return os.path.expanduser("~/Music")

    def _get_music_files(self) -> List[str]:
        """Scan music folder for audio files."""
        if not os.path.exists(self.music_folder):
            logger.warning(f"Music folder not found: {self.music_folder}")
            return []

        # Supported audio file extensions
        extensions = ['*.mp3', '*.wav', '*.flac', '*.ogg', '*.m4a', '*.aac']
        music_files = []

        for ext in extensions:
            music_files.extend(glob.glob(os.path.join(self.music_folder, '**', ext), recursive=True))

        return music_files

    def _build_music_cache(self) -> Dict[str, Any]:
        """Build a cache of music files with metadata."""
        music_files = self._get_music_files()
        cache = {}

        for file_path in music_files:
            try:
                # Extract basic metadata from filename
                filename = os.path.basename(file_path)
                name_without_ext = os.path.splitext(filename)[0]

                cache[file_path] = {
                    'title': name_without_ext,
                    'path': file_path,
                    'artist': 'Unknown',
                    'album': 'Unknown',
                    'duration': 'Unknown'
                }
            except Exception as e:
                logger.error(f"Error processing file {file_path}: {e}")

        return cache

    def _get_music_cache(self) -> Dict[str, Any]:
        """Get music cache, building it if necessary."""
        if self._music_cache is None:
            self._music_cache = self._build_music_cache()
        return self._music_cache

    def play_music_file(self, file_path: str) -> str:
        """Play a specific music file using the system's default player.
        
        Args:
            file_path: Path to the music file to play
            
        Returns:
            Confirmation message or error
        """
        if not os.path.exists(file_path):
            return f"Error: File not found: {file_path}"

        try:
            system = platform.system()

            if system == "Windows":
                # Windows: use start command or os.startfile
                subprocess.Popen(['start', file_path], shell=True)
                return f"Playing {os.path.basename(file_path)} in default player"

            elif system == "Darwin":  # macOS
                # macOS: use open command
                subprocess.Popen(['open', file_path])
                return f"Playing {os.path.basename(file_path)} in default player"

            else:  # Linux and others
                # Linux: use xdg-open
                subprocess.Popen(['xdg-open', file_path])
                return f"Playing {os.path.basename(file_path)} in default player"

        except Exception as e:
            logger.error(f"Failed to play music file {file_path}: {e}")
            return f"Error playing {os.path.basename(file_path)}: {str(e)}"

    def search_music(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """Search music library for tracks.
        
        Args:
            query: Search query (matches against title, artist, album)
            max_results: Maximum number of results to return
            
        Returns:
            List of matching tracks with metadata
        """
        cache = self._get_music_cache()
        results = []

        query_lower = query.lower()

        for file_path, metadata in cache.items():
            # Search in title, artist, and album
            if (query_lower in metadata['title'].lower() or
                query_lower in metadata['artist'].lower() or
                query_lower in metadata['album'].lower()):

                results.append({
                    'title': metadata['title'],
                    'artist': metadata['artist'],
                    'album': metadata['album'],
                    'path': file_path,
                    'duration': metadata['duration']
                })

                if len(results) >= max_results:
                    break

        return results

    def play_song_by_title(self, title: str) -> str:
        """Play a song by its title.
        
        Args:
            title: Title of the song to play
            
        Returns:
            Confirmation message or error
        """
        results = self.search_music(title, max_results=1)

        if not results:
            return f"No song found with title: {title}"

        song = results[0]
        return self.play_music_file(song['path'])

    def get_music_library_stats(self) -> Dict[str, Any]:
        """Get statistics about the music library."""
        cache = self._get_music_cache()

        return {
            'total_songs': len(cache),
            'music_folder': self.music_folder,
            'file_types': list(set(os.path.splitext(f)[1] for f in cache.keys()))
        }

    def set_music_folder(self, folder_path: str) -> str:
        """Set the music folder path.
        
        Args:
            folder_path: Path to the music folder
            
        Returns:
            Confirmation message
        """
        if not os.path.exists(folder_path):
            return f"Error: Folder not found: {folder_path}"

        self.music_folder = folder_path
        self._music_cache = None  # Clear cache to rebuild with new folder

        return f"Music folder set to: {folder_path}"

    def refresh_music_library(self) -> str:
        """Refresh the music library cache.
        
        Returns:
            Confirmation message
        """
        self._music_cache = None
        cache = self._get_music_cache()

        return f"Music library refreshed. Found {len(cache)} songs."


class AdvancedMusicControlSkill:
    """Advanced music control with playlist management."""

    def __init__(self, music_folder: Optional[str] = None):
        """Initialize advanced music control."""
        self.base_control = MusicControlSkill(music_folder)
        self.playlists_file = os.path.join(music_folder or self.base_control._get_default_music_folder(), 'playlists.json')
        self._playlists = self._load_playlists()

    def _load_playlists(self) -> Dict[str, List[str]]:
        """Load playlists from file."""
        try:
            if os.path.exists(self.playlists_file):
                with open(self.playlists_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error loading playlists: {e}")

        return {}

    def _save_playlists(self):
        """Save playlists to file."""
        try:
            os.makedirs(os.path.dirname(self.playlists_file), exist_ok=True)
            with open(self.playlists_file, 'w') as f:
                json.dump(self._playlists, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving playlists: {e}")

    def create_playlist(self, name: str, song_titles: List[str]) -> str:
        """Create a new playlist.
        
        Args:
            name: Playlist name
            song_titles: List of song titles to add
            
        Returns:
            Confirmation message
        """
        # Find songs by title
        playlist_songs = []

        for title in song_titles:
            results = self.base_control.search_music(title, max_results=1)
            if results:
                playlist_songs.append(results[0]['path'])

        self._playlists[name] = playlist_songs
        self._save_playlists()

        return f"Created playlist '{name}' with {len(playlist_songs)} songs"

    def play_playlist(self, name: str) -> str:
        """Play a playlist.
        
        Args:
            name: Playlist name
            
        Returns:
            Confirmation message or error
        """
        if name not in self._playlists:
            return f"Playlist not found: {name}"

        playlist = self._playlists[name]
        if not playlist:
            return f"Playlist '{name}' is empty"

        # Play the first song in the playlist
        return self.base_control.play_music_file(playlist[0])

    def list_playlists(self) -> List[str]:
        """List available playlists."""
        return list(self._playlists.keys())

    def get_playlist_info(self, name: str) -> Dict[str, Any]:
        """Get information about a playlist."""
        if name not in self._playlists:
            return {'error': 'Playlist not found'}

        playlist = self._playlists[name]
        songs_info = []

        for song_path in playlist:
            results = self.base_control.search_music(os.path.basename(song_path), max_results=1)
            if results:
                songs_info.append(results[0])

        return {
            'name': name,
            'song_count': len(playlist),
            'songs': songs_info
        }


# Create instances for easy access
music_control = MusicControlSkill()
advanced_music_control = AdvancedMusicControlSkill()

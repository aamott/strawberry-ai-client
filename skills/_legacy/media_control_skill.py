"""Media playback control skills (legacy).

Delegates platform-specific dispatch to the shared ``media_dispatch`` module
in the repo skill directory.
"""

import sys
from pathlib import Path

# Ensure the repo skills directory is importable so we can reach
# media_control_skill.media_dispatch without requiring a package install.
_skills_dir = Path(__file__).resolve().parent.parent
if str(_skills_dir) not in sys.path:
    sys.path.insert(0, str(_skills_dir))

from media_control_skill.media_dispatch import (  # noqa: E402
    get_system_volume,
    send_media_command,
)


class MediaControlSkill:
    """Controls media playback on the device.

    Legacy wrapper — delegates all platform logic to
    ``media_control_skill.media_dispatch``.
    """

    def play(self) -> str:
        """Resume media playback."""
        return send_media_command("play")

    def pause(self) -> str:
        """Pause media playback."""
        return send_media_command("pause")

    def stop(self) -> str:
        """Stop media playback."""
        return send_media_command("stop")

    def next_track(self) -> str:
        """Skip to the next track."""
        return send_media_command("next")

    def previous_track(self) -> str:
        """Go back to the previous track."""
        return send_media_command("previous")

    def set_volume(self, volume: int) -> str:
        """Set the media volume.

        Args:
            volume: Volume level (0-100)

        Returns:
            Confirmation message

        Raises:
            ValueError: If volume is out of range
        """
        if volume < 0 or volume > 100:
            raise ValueError("Volume must be between 0 and 100")

        return send_media_command(f"volume {volume}")

    def get_volume(self) -> int:
        """Get the current volume level.

        Returns:
            Current volume level (0-100)
        """
        volume = get_system_volume()
        if volume is None:
            return 75
        return volume

    def get_current_track(self) -> dict:
        """Get information about the currently playing track.

        Returns:
            Dictionary with track information
        """
        return {
            "title": "Sample Track",
            "artist": "Sample Artist",
            "album": "Sample Album",
            "duration": "3:45",
            "position": "1:23",
        }


class MusicLibrarySkill:
    """Manages music library and playlists."""

    def search_songs(self, query: str, max_results: int = 10) -> list:
        """Search for songs in the music library.

        Args:
            query: Search query
            max_results: Maximum number of results

        Returns:
            List of matching songs
        """
        # Simulated search results
        return [
            {
                "title": f"Song matching '{query}'",
                "artist": "Sample Artist",
                "album": "Sample Album",
                "duration": "3:30",
            }
        ][:max_results]

    def create_playlist(self, name: str, song_titles: list) -> str:
        """Create a new playlist.

        Args:
            name: Playlist name
            song_titles: List of song titles to add

        Returns:
            Confirmation message
        """
        return f"Created playlist '{name}' with {len(song_titles)} songs"

    def play_playlist(self, name: str) -> str:
        """Play a specific playlist.

        Args:
            name: Playlist name

        Returns:
            Confirmation message
        """
        return f"Now playing playlist '{name}'"

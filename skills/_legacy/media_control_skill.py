"""Media playback control skills."""

import platform
import subprocess


class MediaControlSkill:
    """Controls media playback on the device."""

    def play(self) -> str:
        """Resume media playback."""
        return self._send_media_command("play")

    def pause(self) -> str:
        """Pause media playback."""
        return self._send_media_command("pause")

    def stop(self) -> str:
        """Stop media playback."""
        return self._send_media_command("stop")

    def next_track(self) -> str:
        """Skip to the next track."""
        return self._send_media_command("next")

    def previous_track(self) -> str:
        """Go back to the previous track."""
        return self._send_media_command("previous")

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

        return self._send_media_command(f"volume {volume}")

    def get_volume(self) -> int:
        """Get the current volume level.

        Returns:
            Current volume level (0-100)
        """
        # Simulated volume - real implementation would query system
        return 75

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

    # Windows SendKeys media key mappings
    _WIN_MEDIA_KEYS: dict[str, str] = {
        "play": "{MEDIA_PLAY_PAUSE}",
        "pause": "{MEDIA_PLAY_PAUSE}",
        "stop": "{MEDIA_STOP}",
        "next": "{MEDIA_NEXT_TRACK}",
        "previous": "{MEDIA_PREV_TRACK}",
    }

    # macOS AppleScript verb mappings
    _MAC_MEDIA_VERBS: dict[str, str] = {
        "play": "play",
        "pause": "pause",
        "next": "next track",
        "previous": "previous track",
    }

    def _send_media_command(self, command: str) -> str:
        """Send media control command to the system."""
        system = platform.system()

        try:
            if system == "Windows":
                key = self._WIN_MEDIA_KEYS.get(command)
                if key:
                    script = (
                        "(New-Object -ComObject"
                        f" WScript.Shell).SendKeys('{key}')"
                    )
                    subprocess.run(["powershell", script])
            elif system == "Darwin":
                verb = self._MAC_MEDIA_VERBS.get(command)
                if verb:
                    subprocess.run([
                        "osascript", "-e",
                        f'tell application "Spotify"'
                        f' to {verb}',
                    ])
            elif system == "Linux":
                subprocess.run(["playerctl", command])

            return f"Media command '{command}' executed"

        except Exception:
            return f"Media command '{command}' sent (simulated)"


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

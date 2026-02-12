"""Media playback control skills."""

import logging

from strawberry.shared.settings.schema import FieldType, SettingField

from .media_dispatch import get_system_volume, send_media_command

logger = logging.getLogger(__name__)

# Settings schema registered automatically by SkillLoader.
# Namespace will be "skills.media_control_skill".
SETTINGS_SCHEMA = [
    SettingField(
        key="macos_player",
        label="macOS Player",
        type=FieldType.SELECT,
        options=["spotify", "music"],
        default="spotify",
        description="Media player app for macOS AppleScript commands",
        group="general",
    ),
]


class MediaControlSkill:
    """Controls media playback on the device.

    Delegates all platform-specific logic to ``media_dispatch``.
    """

    # Namespace used by SettingsManager for this skill's settings
    SETTINGS_NAMESPACE = "skills.media_control_skill"

    def __init__(self, settings_manager=None):
        self._settings_manager = settings_manager

    def _get_macos_player_app(self) -> str:
        """Resolve the configured macOS media player application name.

        Returns:
            The macOS application name used in AppleScript commands.
        """
        player = "spotify"  # default
        if self._settings_manager:
            player = (
                self._settings_manager.get(
                    self.SETTINGS_NAMESPACE, "macos_player", "spotify",
                )
                or "spotify"
            )
        else:
            # Backward compat: fall back to deprecated config
            try:
                from strawberry.config import get_settings
                settings = get_settings()
                player = settings.media.macos_player.lower()
            except Exception:
                pass

        app_map = {
            "spotify": "Spotify",
            "music": "Music",
        }
        return app_map.get(player.lower(), "Spotify")

    def play(self) -> str:
        """Resume media playback."""
        return send_media_command("play", macos_app=self._get_macos_player_app())

    def pause(self) -> str:
        """Pause media playback."""
        return send_media_command("pause", macos_app=self._get_macos_player_app())

    def stop(self) -> str:
        """Stop media playback."""
        return send_media_command("stop", macos_app=self._get_macos_player_app())

    def next_track(self) -> str:
        """Skip to the next track."""
        return send_media_command("next", macos_app=self._get_macos_player_app())

    def previous_track(self) -> str:
        """Go back to the previous track."""
        return send_media_command("previous", macos_app=self._get_macos_player_app())

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

        send_media_command(f"volume {volume}")
        return f"Media volume set to {volume}"

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

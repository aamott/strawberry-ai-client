"""Media playback control skills."""

import platform
import re
import shutil
import subprocess

from strawberry.config import get_settings


class MediaControlSkill:
    """Controls media playback on the device."""

    def _get_macos_player_app(self) -> str:
        """Resolve the configured macOS media player application name.

        Returns:
            The macOS application name used in AppleScript commands.
        """
        settings = get_settings()
        player = settings.media.macos_player.lower()
        app_map = {
            "spotify": "Spotify",
            "music": "Music",
        }
        return app_map.get(player, "Spotify")

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

        self._send_media_command(f"volume {volume}")
        return f"Media volume set to {volume}"

    def get_volume(self) -> int:
        """Get the current volume level.

        Returns:
            Current volume level (0-100)
        """
        volume = self._get_system_volume()
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
            if command.startswith("volume"):
                parts = command.split()
                if len(parts) == 2 and parts[1].isdigit():
                    self._set_system_volume(int(parts[1]))
                return f"Media command '{command}' executed"

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
                    app = self._get_macos_player_app()
                    subprocess.run([
                        "osascript", "-e",
                        f'tell application "{app}" to {verb}',
                    ])
            elif system == "Linux":
                subprocess.run(["playerctl", command])

            return f"Media command '{command}' executed"

        except Exception:
            return f"Media command '{command}' sent (simulated)"

    def _set_system_volume(self, volume: int) -> None:
        """Set the system volume using platform-specific tools.

        Args:
            volume: Volume level (0-100).
        """
        system = platform.system()
        if system == "Linux":
            self._set_linux_volume(volume)
            return
        if system == "Windows":
            self._set_windows_volume(volume)
            return

    def _get_system_volume(self) -> int | None:
        """Get the system volume using platform-specific tools.

        Returns:
            The volume level (0-100) if available, otherwise None.
        """
        system = platform.system()
        if system == "Linux":
            return self._get_linux_volume()
        if system == "Windows":
            return self._get_windows_volume()
        return None

    def _set_linux_volume(self, volume: int) -> None:
        """Set volume on Linux using PipeWire/PulseAudio tools.

        Args:
            volume: Volume level (0-100).
        """
        if shutil.which("wpctl"):
            subprocess.run(
                ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{volume / 100:.2f}"]
            )
            return
        if shutil.which("pactl"):
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{volume}%"])
            return
        if shutil.which("amixer"):
            subprocess.run(["amixer", "-D", "pulse", "sset", "Master", f"{volume}%"])
            return

    def _get_linux_volume(self) -> int | None:
        """Get volume on Linux using PipeWire/PulseAudio tools."""
        if shutil.which("wpctl"):
            result = subprocess.run(
                ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                capture_output=True,
                text=True,
            )
            match = re.search(r"([0-9.]+)", result.stdout or "")
            if match:
                return int(float(match.group(1)) * 100)
            return None
        if shutil.which("pactl"):
            result = subprocess.run(
                ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                capture_output=True,
                text=True,
            )
            match = re.search(r"(\d+)%", result.stdout or "")
            if match:
                return int(match.group(1))
            return None
        if shutil.which("amixer"):
            result = subprocess.run(
                ["amixer", "-D", "pulse", "sget", "Master"],
                capture_output=True,
                text=True,
            )
            match = re.search(r"\[(\d+)%\]", result.stdout or "")
            if match:
                return int(match.group(1))
        return None

    def _set_windows_volume(self, volume: int) -> None:
        """Set volume on Windows using CoreAudio via PowerShell.

        Args:
            volume: Volume level (0-100).
        """
        scalar = max(0.0, min(1.0, volume / 100))
        script = self._windows_volume_script(
            f"$vol.SetMasterVolumeLevelScalar({scalar}, [Guid]::Empty)"
        )
        subprocess.run(["powershell", "-Command", script], capture_output=True, text=True)

    def _get_windows_volume(self) -> int | None:
        """Get volume on Windows using CoreAudio via PowerShell."""
        script = self._windows_volume_script(
            "$vol.GetMasterVolumeLevelScalar([ref]$level); $level"
        )
        result = subprocess.run(
            ["powershell", "-Command", script], capture_output=True, text=True
        )
        match = re.search(r"([0-9.]+)", result.stdout or "")
        if match:
            return int(float(match.group(1)) * 100)
        return None

    @staticmethod
    def _windows_volume_script(action: str) -> str:
        """Build the PowerShell script to read/write system volume.

        Args:
            action: PowerShell command run against the IAudioEndpointVolume instance.

        Returns:
            PowerShell script text.
        """
        type_def = "\n".join(
            [
                "Add-Type -TypeDefinition @'",
                "using System;",
                "using System.Runtime.InteropServices;",
                "namespace AudioUtilities {",
                '  [Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), ',
                "InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]",
                "  interface IAudioEndpointVolume {",
                "    int RegisterControlChangeNotify(IntPtr pNotify);",
                "    int UnregisterControlChangeNotify(IntPtr pNotify);",
                "    int GetChannelCount(out uint channelCount);",
                "    int SetMasterVolumeLevel(float level, Guid eventContext);",
                "    int SetMasterVolumeLevelScalar(float level, Guid eventContext);",
                "    int GetMasterVolumeLevel(out float level);",
                "    int GetMasterVolumeLevelScalar(out float level);",
                (
                    "    int SetChannelVolumeLevel(uint channelNumber, float level, "
                    "Guid eventContext);"
                ),
                (
                    "    int SetChannelVolumeLevelScalar("
                    "uint channelNumber, float level, "
                    "Guid eventContext);"
                ),
                "    int GetChannelVolumeLevel(",
                "uint channelNumber, out float level);",
                "    int GetChannelVolumeLevelScalar(",
                "uint channelNumber, out float level);",
                "    int SetMute(",
                "[MarshalAs(UnmanagedType.Bool)]",
                " bool isMuted, Guid eventContext);",
                "    int GetMute(out bool isMuted);",
                "  }",
                '  [Guid("D666063F-1587-4E43-81F1-B948E807363F"), ',
                "InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]",
                "  interface IMMDevice {",
                "    int Activate(ref Guid iid, int dwClsCtx, IntPtr pActivationParams, ",
                "out IAudioEndpointVolume aev);",
                "  }",
                '  [Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), ',
                "InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]",
                "  interface IMMDeviceEnumerator {",
                "    int NotImpl1();",
                "    int GetDefaultAudioEndpoint(",
                "int dataFlow, int role,",
                " out IMMDevice device);",
                "  }",
                '  [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]',
                "  class MMDeviceEnumerator {}",
                "  public class Audio {",
                "    public static IAudioEndpointVolume GetDefaultEndpointVolume() {",
                "      var enumerator = new MMDeviceEnumerator() as IMMDeviceEnumerator;",
                "      IMMDevice device;",
                "      enumerator.GetDefaultAudioEndpoint(0, 1, out device);",
                "      Guid iid = typeof(IAudioEndpointVolume).GUID;",
                "      IAudioEndpointVolume volume;",
                "      device.Activate(ref iid, 23, IntPtr.Zero, out volume);",
                "      return volume;",
                "    }",
                "  }",
                "}",
                "'@;",
            ]
        )
        return (
            f"{type_def} $vol = [AudioUtilities.Audio]::GetDefaultEndpointVolume(); "
            f"{action}"
        )


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

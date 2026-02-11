"""Shared media command dispatcher with per-platform adapters.

Provides a single ``send_media_command`` function that routes play/pause/
stop/next/previous/volume commands to the correct platform backend
(Windows SendKeys, macOS AppleScript, Linux playerctl).

Both the repo skill and the legacy skill import from here so the
platform-specific logic lives in exactly one place.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
from typing import Optional

# ---------------------------------------------------------------------------
# Platform dispatch tables
# ---------------------------------------------------------------------------

# Windows SendKeys media key mappings
WIN_MEDIA_KEYS: dict[str, str] = {
    "play": "{MEDIA_PLAY_PAUSE}",
    "pause": "{MEDIA_PLAY_PAUSE}",
    "stop": "{MEDIA_STOP}",
    "next": "{MEDIA_NEXT_TRACK}",
    "previous": "{MEDIA_PREV_TRACK}",
}

# macOS AppleScript verb mappings
MAC_MEDIA_VERBS: dict[str, str] = {
    "play": "play",
    "pause": "pause",
    "next": "next track",
    "previous": "previous track",
}


# ---------------------------------------------------------------------------
# Core dispatcher
# ---------------------------------------------------------------------------


def send_media_command(command: str, *, macos_app: str = "Spotify") -> str:
    """Send a media-control command to the system.

    Args:
        command: One of "play", "pause", "stop", "next", "previous",
                 or "volume <0-100>".
        macos_app: macOS application name for AppleScript (default "Spotify").

    Returns:
        Human-readable result string.
    """
    system = platform.system()

    try:
        # Handle volume commands separately
        if command.startswith("volume"):
            parts = command.split()
            if len(parts) == 2 and parts[1].isdigit():
                set_system_volume(int(parts[1]))
            return f"Media command '{command}' executed"

        if system == "Windows":
            _send_windows(command)
        elif system == "Darwin":
            _send_macos(command, macos_app)
        elif system == "Linux":
            _send_linux(command)

        return f"Media command '{command}' executed"

    except Exception:
        return f"Media command '{command}' sent (simulated)"


# ---------------------------------------------------------------------------
# Platform adapters — playback
# ---------------------------------------------------------------------------


def _send_windows(command: str) -> None:
    """Send a media key via PowerShell SendKeys on Windows."""
    key = WIN_MEDIA_KEYS.get(command)
    if key:
        script = f"(New-Object -ComObject WScript.Shell).SendKeys('{key}')"
        subprocess.run(["powershell", script])


def _send_macos(command: str, app: str) -> None:
    """Send an AppleScript verb on macOS."""
    verb = MAC_MEDIA_VERBS.get(command)
    if verb:
        subprocess.run(
            ["osascript", "-e", f'tell application "{app}" to {verb}']
        )


def _send_linux(command: str) -> None:
    """Send a playerctl command on Linux."""
    subprocess.run(["playerctl", command])


# ---------------------------------------------------------------------------
# Platform adapters — volume
# ---------------------------------------------------------------------------


def set_system_volume(volume: int) -> None:
    """Set the system volume (0-100) using platform-specific tools.

    Args:
        volume: Volume level (0-100).
    """
    system = platform.system()
    if system == "Linux":
        _set_linux_volume(volume)
    elif system == "Windows":
        _set_windows_volume(volume)


def get_system_volume() -> Optional[int]:
    """Get the system volume (0-100) using platform-specific tools.

    Returns:
        Volume level or None if unavailable.
    """
    system = platform.system()
    if system == "Linux":
        return _get_linux_volume()
    if system == "Windows":
        return _get_windows_volume()
    return None


# -- Linux volume ---------------------------------------------------------


def _set_linux_volume(volume: int) -> None:
    """Set volume on Linux using PipeWire/PulseAudio tools."""
    if shutil.which("wpctl"):
        subprocess.run(
            ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{volume / 100:.2f}"]
        )
        return
    if shutil.which("pactl"):
        subprocess.run(
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{volume}%"]
        )
        return
    if shutil.which("amixer"):
        subprocess.run(
            ["amixer", "-D", "pulse", "sset", "Master", f"{volume}%"]
        )
        return


def _get_linux_volume() -> Optional[int]:
    """Get volume on Linux using PipeWire/PulseAudio tools."""
    if shutil.which("wpctl"):
        result = subprocess.run(
            ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
            capture_output=True, text=True,
        )
        match = re.search(r"([0-9.]+)", result.stdout or "")
        if match:
            return int(float(match.group(1)) * 100)
        return None
    if shutil.which("pactl"):
        result = subprocess.run(
            ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
            capture_output=True, text=True,
        )
        match = re.search(r"(\d+)%", result.stdout or "")
        if match:
            return int(match.group(1))
        return None
    if shutil.which("amixer"):
        result = subprocess.run(
            ["amixer", "-D", "pulse", "sget", "Master"],
            capture_output=True, text=True,
        )
        match = re.search(r"\[(\d+)%\]", result.stdout or "")
        if match:
            return int(match.group(1))
    return None


# -- Windows volume -------------------------------------------------------


def _set_windows_volume(volume: int) -> None:
    """Set volume on Windows using CoreAudio via PowerShell."""
    scalar = max(0.0, min(1.0, volume / 100))
    script = _windows_volume_script(
        f"$vol.SetMasterVolumeLevelScalar({scalar}, [Guid]::Empty)"
    )
    subprocess.run(
        ["powershell", "-Command", script],
        capture_output=True, text=True,
    )


def _get_windows_volume() -> Optional[int]:
    """Get volume on Windows using CoreAudio via PowerShell."""
    script = _windows_volume_script(
        "$vol.GetMasterVolumeLevelScalar([ref]$level); $level"
    )
    result = subprocess.run(
        ["powershell", "-Command", script],
        capture_output=True, text=True,
    )
    match = re.search(r"([0-9.]+)", result.stdout or "")
    if match:
        return int(float(match.group(1)) * 100)
    return None


def _windows_volume_script(action: str) -> str:
    """Build the PowerShell script to read/write system volume.

    Args:
        action: PowerShell command run against the IAudioEndpointVolume.

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

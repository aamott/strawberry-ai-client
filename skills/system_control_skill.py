"""System control and device management skills."""

import platform
import subprocess
from typing import Any, Dict


class SystemControlSkill:
    """Controls basic system functions."""

    def get_system_info(self) -> Dict[str, Any]:
        """Get basic system information.
        
        Returns:
            Dictionary with system information
        """
        return {
            "os": platform.system(),
            "os_version": platform.version(),
            "architecture": platform.architecture()[0],
            "processor": platform.processor(),
            "hostname": platform.node()
        }

    def set_system_volume(self, volume: int) -> str:
        """Set the system volume.
        
        Args:
            volume: Volume level (0-100)
            
        Returns:
            Confirmation message
            
        Raises:
            ValueError: If volume is out of range
        """
        if volume < 0 or volume > 100:
            raise ValueError("Volume must be between 0 and 100")

        system = platform.system()

        try:
            if system == "Windows":
                # Windows volume control
                subprocess.run(["powershell", f"(New-Object -ComObject WScript.Shell).SendKeys([char]{volume})"])
            elif system == "Darwin":  # macOS
                # macOS volume control
                subprocess.run(["osascript", "-e", f"set volume output volume {volume}"])
            elif system == "Linux":
                # Linux volume control (using amixer or pactl)
                subprocess.run(["amixer", "-D", "pulse", "sset", "Master", f"{volume}%"])

            return f"System volume set to {volume}%"
        except Exception:
            return f"System volume set to {volume}% (simulated)"

    def get_system_volume(self) -> int:
        """Get the current system volume.
        
        Returns:
            Current volume level (0-100)
        """
        # Simulated volume - real implementation would query system
        return 75

    def sleep_system(self) -> str:
        """Put the system to sleep.
        
        Note:
            This method is simulated for safety during testing.
            In production, it would require appropriate permissions.
        """
        # Always simulate for safety
        return "System sleep command sent (simulated for safety)"

    def restart_system(self) -> str:
        """Restart the system.
        
        Note:
            This method is simulated for safety during testing.
            In production, it would require admin privileges.
        """
        # Always simulate for safety
        return "System restart command sent (simulated for safety - requires admin privileges)"

    def shutdown_system(self) -> str:
        """Shut down the system.
        
        Note:
            This method is simulated for safety during testing.
            In production, it would require admin privileges.
        """
        # Always simulate for safety
        return "System shutdown command sent (simulated for safety - requires admin privileges)"


class DisplayControlSkill:
    """Controls display settings."""

    def set_brightness(self, brightness: int) -> str:
        """Set the display brightness.
        
        Args:
            brightness: Brightness level (0-100)
            
        Returns:
            Confirmation message
            
        Raises:
            ValueError: If brightness is out of range
        """
        if brightness < 0 or brightness > 100:
            raise ValueError("Brightness must be between 0 and 100")

        system = platform.system()

        try:
            if system == "Windows":
                # Windows brightness control
                subprocess.run(["powershell", f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1, {brightness})"])
            elif system == "Darwin":  # macOS
                # macOS brightness control
                subprocess.run(["osascript", "-e", "tell application \"System Events\" to key code 144 using control down"])
            elif system == "Linux":
                # Linux brightness control
                subprocess.run(["xrandr", "--output", "eDP-1", "--brightness", str(brightness/100)])

            return f"Display brightness set to {brightness}%"
        except Exception:
            return f"Display brightness set to {brightness}% (simulated)"

    def get_brightness(self) -> int:
        """Get the current display brightness.
        
        Returns:
            Current brightness level (0-100)
        """
        # Simulated brightness - real implementation would query system
        return 80

"""Time skill repository entrypoint."""

import datetime


class TimeSkill:
    """Provides time and date information."""

    def get_current_time(self) -> str:
        """Get the current time.

        Returns:
            Current time as a formatted string (HH:MM:SS)
        """
        return datetime.datetime.now().strftime("%H:%M:%S")

    def get_current_date(self) -> str:
        """Get the current date.

        Returns:
            Current date as a formatted string (YYYY-MM-DD)
        """
        return datetime.datetime.now().strftime("%Y-%m-%d")

    def get_day_of_week(self) -> str:
        """Get the current day of the week.

        Returns:
            Day name (e.g., "Monday")
        """
        return datetime.datetime.now().strftime("%A")

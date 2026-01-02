"""Example skill demonstrating the skill structure."""

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


class CalculatorSkill:
    """Basic calculator operations."""

    def add(self, a: float, b: float) -> float:
        """Add two numbers.

        Args:
            a: First number
            b: Second number

        Returns:
            Sum of a and b
        """
        return a + b

    def subtract(self, a: float, b: float) -> float:
        """Subtract b from a.

        Args:
            a: First number
            b: Second number

        Returns:
            Difference (a - b)
        """
        return a - b

    def multiply(self, a: float, b: float) -> float:
        """Multiply two numbers.

        Args:
            a: First number
            b: Second number

        Returns:
            Product of a and b
        """
        return a * b

    def divide(self, a: float, b: float) -> float:
        """Divide a by b.

        Args:
            a: Dividend
            b: Divisor

        Returns:
            Quotient (a / b)

        Raises:
            ValueError: If b is zero
        """
        if b == 0:
            raise ValueError("Cannot divide by zero")
        return a / b


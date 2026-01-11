"""Calculator skill repository entrypoint."""


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

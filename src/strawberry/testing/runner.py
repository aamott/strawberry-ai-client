"""Custom test runner with clean, minimal output.

Runs tests and shows only what matters:
- ✓ for passing tests
- ✗ with a short error description for failures
- Summary at the end
"""

import inspect
import sys
import time
import traceback
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Callable, List, Optional


@dataclass
class TestResult:
    """Result of a single test."""
    name: str
    passed: bool
    duration_ms: float
    error: Optional[str] = None
    error_line: Optional[str] = None


@dataclass
class TestSuite:
    """Collection of test results."""
    results: List[TestResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def duration_ms(self) -> float:
        return sum(r.duration_ms for r in self.results)


class TestRunner:
    """Minimal test runner with clean output."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.suite = TestSuite()

    def run_test(self, test_func: Callable, name: str) -> TestResult:
        """Run a single test function."""
        start = time.perf_counter()

        try:
            test_func()
            duration = (time.perf_counter() - start) * 1000
            return TestResult(name=name, passed=True, duration_ms=duration)

        except AssertionError as e:
            duration = (time.perf_counter() - start) * 1000
            # Get the line that failed
            tb = traceback.extract_tb(sys.exc_info()[2])
            error_line = None
            for frame in reversed(tb):
                if "test_" in frame.filename:
                    error_line = f"{Path(frame.filename).name}:{frame.lineno}"
                    break

            error_msg = str(e) if str(e) else "Assertion failed"
            return TestResult(
                name=name,
                passed=False,
                duration_ms=duration,
                error=error_msg,
                error_line=error_line
            )

        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            tb = traceback.extract_tb(sys.exc_info()[2])
            error_line = None
            for frame in reversed(tb):
                if "test_" in frame.filename or "strawberry" in frame.filename:
                    error_line = f"{Path(frame.filename).name}:{frame.lineno}"
                    break

            return TestResult(
                name=name,
                passed=False,
                duration_ms=duration,
                error=f"{type(e).__name__}: {e}",
                error_line=error_line
            )

    def discover_tests(self, test_dir: Path) -> List[tuple[str, Callable]]:
        """Discover all test functions in test directory."""
        tests = []

        if not test_dir.exists():
            return tests

        # Add test dir to path
        sys.path.insert(0, str(test_dir.parent))

        for test_file in sorted(test_dir.glob("test_*.py")):
            module_name = test_file.stem
            try:
                module = import_module(f"tests.{module_name}")

                for name, obj in inspect.getmembers(module):
                    if name.startswith("test_") and callable(obj):
                        full_name = f"{module_name}.{name}"
                        tests.append((full_name, obj))

            except Exception as e:
                print(f"  ⚠ Could not load {test_file.name}: {e}")

        return tests

    def run_all(self, test_dir: Path) -> TestSuite:
        """Run all discovered tests."""
        tests = self.discover_tests(test_dir)

        if not tests:
            print("No tests found.")
            return self.suite

        print(f"Running {len(tests)} tests...\n")

        current_module = None
        for name, test_func in tests:
            module = name.split(".")[0]

            # Print module header
            if module != current_module:
                if current_module is not None:
                    print()  # Blank line between modules
                print(f"  {module}")
                current_module = module

            # Run test
            result = self.run_test(test_func, name)
            self.suite.results.append(result)

            # Print result
            test_name = name.split(".", 1)[1]
            if result.passed:
                if self.verbose:
                    print(f"    ✓ {test_name} ({result.duration_ms:.1f}ms)")
                else:
                    print(f"    ✓ {test_name}")
            else:
                print(f"    ✗ {test_name}")
                if result.error_line:
                    print(f"      └─ {result.error_line}: {result.error}")
                else:
                    print(f"      └─ {result.error}")

        return self.suite

    def print_summary(self):
        """Print test summary."""
        print()
        print("─" * 50)

        if self.suite.failed == 0:
            print(f"✓ {self.suite.passed} passed ({self.suite.duration_ms:.0f}ms)")
        else:
            print(f"✗ {self.suite.failed} failed, {self.suite.passed} passed ({self.suite.duration_ms:.0f}ms)")

            # List failed tests
            print("\nFailed tests:")
            for r in self.suite.results:
                if not r.passed:
                    print(f"  • {r.name}")


def main() -> int:
    """Run tests with clean output."""
    # Find project root (where pyproject.toml is)
    current = Path(__file__).resolve()
    project_root = current.parent.parent.parent.parent  # src/strawberry/testing -> project root
    test_dir = project_root / "tests"

    # Check for verbose flag
    verbose = "-v" in sys.argv or "--verbose" in sys.argv

    print("Strawberry AI - Test Runner")
    print("─" * 50)

    runner = TestRunner(verbose=verbose)
    runner.run_all(test_dir)
    runner.print_summary()

    return 0 if runner.suite.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())


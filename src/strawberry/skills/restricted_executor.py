"""Thread-safe restricted Python code executor using RestrictedPython.

This module provides a secure way to execute LLM-generated Python code
without using global `sys.stdout` manipulation. Each execution gets its
own isolated output buffer, making it safe for concurrent use.
"""

import logging
import warnings
from dataclasses import dataclass
from typing import Any, Dict, Optional

from RestrictedPython import compile_restricted, safe_builtins
from RestrictedPython.Eval import default_guarded_getitem, default_guarded_getiter
from RestrictedPython.Guards import (
    guarded_iter_unpack_sequence,
    guarded_unpack_sequence,
    safer_getattr,
)
from RestrictedPython.PrintCollector import PrintCollector

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of executing restricted code."""

    success: bool
    output: str = ""
    error: Optional[str] = None


def execute_restricted(
    code: str,
    device_proxy: Any,
    device_manager: Optional[Any] = None,
) -> ExecutionResult:
    """Execute user code in a thread-safe, restricted environment.

    This function compiles and runs Python code using RestrictedPython,
    which prevents dangerous operations like imports and attribute access
    to dunder methods.

    Output is captured via RestrictedPython's PrintCollector - the `print()`
    statements are collected into a local variable called `printed`.

    Args:
        code: Python code to execute
        device_proxy: The `device` object exposing local skills
        device_manager: Optional `devices` object for remote skills

    Returns:
        ExecutionResult with success status, output, or error message
    """
    # Build safe builtins
    restricted_builtins: Dict[str, Any] = dict(safe_builtins)

    # Add common safe builtins that RestrictedPython's safe_builtins might exclude
    # but are needed for typical skill usage
    restricted_builtins.update(
        {
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "dict": dict,
            "list": list,
            "tuple": tuple,
            "set": set,
            "len": len,
            "range": range,
            "min": min,
            "max": max,
            "sum": sum,
            "abs": abs,
            "round": round,
            "repr": repr,
            "enumerate": enumerate,
            "zip": zip,
            "sorted": sorted,
            "any": any,
            "all": all,
            "Exception": Exception,
            "ValueError": ValueError,
            "TypeError": TypeError,
        }
    )

    # Remove dangerous builtins even if present in safe_builtins.
    for name in ("__import__", "open", "eval", "exec", "compile", "input"):
        restricted_builtins.pop(name, None)

    # Local variables dict - PrintCollector stores output in 'printed'
    local_vars: Dict[str, Any] = {}

    # Build globals for execution
    exec_globals: Dict[str, Any] = {
        "__builtins__": restricted_builtins,
        # RestrictedPython guard functions for iteration and attribute access
        "_getiter_": default_guarded_getiter,
        "_getitem_": default_guarded_getitem,
        "_iter_unpack_sequence_": guarded_iter_unpack_sequence,
        "_unpack_sequence_": guarded_unpack_sequence,
        "_getattr_": safer_getattr,
        # RestrictedPython rewrites print() to use PrintCollector
        # _print_ is the class, it creates 'printed' in local scope
        "_print_": PrintCollector,
        # Skill proxies
        "device": device_proxy,
    }

    # Add remote device manager if available
    if device_manager is not None:
        exec_globals["devices"] = device_manager
        exec_globals["device_manager"] = device_manager

    try:
        # Compile with RestrictedPython (this adds security guards).
        # RestrictedPython emits a SyntaxWarning if `print()` is used without
        # reading the injected `printed` variable. We collect output manually,
        # so suppress that warning to avoid noisy test output.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"Line .* Prints, but never reads 'printed' variable.",
                category=SyntaxWarning,
            )
            # compile_restricted returns bytecode directly (or None on failure)
            byte_code = compile_restricted(
                source=code,
                filename="<llm_code>",
                mode="exec",
            )

        # compile_restricted returns None if the code is invalid
        if byte_code is None:
            return ExecutionResult(success=False, error="Compile error: Invalid code")

        # Execute in our restricted environment
        # Pass local_vars so we can retrieve '_print' afterwards
        exec(byte_code, exec_globals, local_vars)

        # PrintCollector stores output in local variable '_print'
        # The .txt attribute is a list of printed strings
        print_collector = local_vars.get("_print")
        if print_collector is not None and hasattr(print_collector, "txt"):
            output = "".join(print_collector.txt).strip()
        else:
            output = "(no output)"

        return ExecutionResult(success=True, output=output or "(no output)")

    except SyntaxError as e:
        return ExecutionResult(success=False, error=f"SyntaxError: {e}")
    except Exception as e:
        return ExecutionResult(success=False, error=f"Execution error: {e}")


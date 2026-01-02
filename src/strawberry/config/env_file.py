"""Helpers for reading and writing .env files.

This module is intentionally lightweight and does not depend on any external
formatting tools. It preserves comments and unknown keys when updating values.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class EnvLine:
    kind: str  # comment | blank | kv
    raw: str
    key: Optional[str] = None
    value: Optional[str] = None


def _parse_env_line(line: str) -> EnvLine:
    stripped = line.strip()
    if not stripped:
        return EnvLine(kind="blank", raw=line)
    if stripped.startswith("#"):
        return EnvLine(kind="comment", raw=line)

    if "=" not in line:
        return EnvLine(kind="comment", raw=line)

    key, value = line.split("=", 1)
    key = key.strip()
    value = value.strip()

    if value.startswith('"') and value.endswith('"') and len(value) >= 2:
        value = value[1:-1].replace("\\\"", '"')

    return EnvLine(kind="kv", raw=line, key=key, value=value)


def read_env_file(env_path: Path) -> Tuple[Dict[str, str], List[EnvLine]]:
    """Read an .env file.

    Returns:
        (values, lines)
    """
    if not env_path.exists():
        return {}, []

    text = env_path.read_text(encoding="utf-8")
    lines = [_parse_env_line(line) for line in text.splitlines(keepends=True)]

    values: Dict[str, str] = {}
    for ln in lines:
        if ln.kind == "kv" and ln.key is not None and ln.value is not None:
            values[ln.key] = ln.value

    return values, lines


def _format_env_value(value: str) -> str:
    if value == "":
        return ""

    needs_quotes = any(ch.isspace() for ch in value) or "#" in value or '"' in value
    if not needs_quotes:
        return value

    escaped = value.replace('"', "\\\"")
    return f'"{escaped}"'


def update_env_file(env_path: Path, updates: Dict[str, Optional[str]]) -> None:
    """Update an .env file in place.

    Args:
        env_path: Path to .env
        updates: Mapping of KEY -> value. If value is None, the key is removed.

    Notes:
        - Preserves comments and unknown keys.
        - Appends new keys at the end of the file.
    """
    current, lines = read_env_file(env_path)

    remaining_updates = dict(updates)
    new_lines: List[str] = []

    for ln in lines:
        if ln.kind != "kv" or not ln.key:
            new_lines.append(ln.raw)
            continue

        if ln.key not in remaining_updates:
            new_lines.append(ln.raw)
            continue

        new_val = remaining_updates.pop(ln.key)
        if new_val is None:
            continue

        formatted = _format_env_value(new_val)
        new_lines.append(f"{ln.key}={formatted}\n")

    for key, val in remaining_updates.items():
        if val is None:
            continue
        formatted = _format_env_value(val)
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] = new_lines[-1] + "\n"
        new_lines.append(f"{key}={formatted}\n")

    if not new_lines:
        env_path.write_text("", encoding="utf-8")
        return

    text = "".join(new_lines)
    if not text.endswith("\n"):
        text += "\n"

    env_path.write_text(text, encoding="utf-8")

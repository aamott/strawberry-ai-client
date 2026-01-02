"""Helpers for updating YAML config files while preserving comments.

We avoid rewriting the entire YAML structure (which would drop comments and
formatting) by applying targeted line-based updates for known scalar fields.

Assumptions:
- 2-space indentation
- Keys are simple strings without quoting
- Updated values are scalars (str/bool/int/float)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class YamlUpdate:
    path: Tuple[str, ...]
    value: Any


def _format_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)

    text = str(value)
    needs_quotes = (
        text == ""
        or any(ch.isspace() for ch in text)
        or text.startswith("{")
        or text.startswith("[")
        or ":" in text
        or "#" in text
        or '"' in text
    )
    if not needs_quotes:
        return text

    escaped = text.replace('"', "\\\"")
    return f'"{escaped}"'


def _indent(level: int) -> str:
    return " " * (level * 2)


def _split_inline_comment(line: str) -> Tuple[str, str]:
    # Keep common pattern of inline comments: "...  # comment"
    if "#" not in line:
        return line.rstrip("\n"), ""

    # Very small heuristic: split on "  #" first, otherwise " #".
    for token in ("  #", " #"):
        if token in line:
            left, right = line.split(token, 1)
            return left.rstrip("\n"), token + right.rstrip("\n")

    return line.rstrip("\n"), ""


def _find_block(
    lines: List[str],
    key: str,
    indent_level: int,
    start_idx: int,
    end_idx: int,
) -> Optional[int]:
    prefix = f"{_indent(indent_level)}{key}:"
    for i in range(start_idx, end_idx):
        if lines[i].startswith(prefix):
            return i
    return None


def _find_block_end(lines: List[str], indent_level: int, start_idx: int) -> int:
    parent_indent = _indent(indent_level)
    i = start_idx + 1
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        current_indent_len = len(line) - len(line.lstrip(" "))
        if current_indent_len <= len(parent_indent):
            return i

        i += 1

    return len(lines)


def _set_scalar_in_block(
    lines: List[str],
    key: str,
    value: Any,
    indent_level: int,
    start_idx: int,
    end_idx: int,
) -> None:
    line_idx = _find_block(
        lines,
        key=key,
        indent_level=indent_level,
        start_idx=start_idx,
        end_idx=end_idx,
    )
    formatted = _format_scalar(value)

    if line_idx is not None:
        existing, comment = _split_inline_comment(lines[line_idx])
        new_line = f"{_indent(indent_level)}{key}: {formatted}{comment}\n"
        lines[line_idx] = new_line
        return

    insert_at = end_idx
    while insert_at > start_idx and not lines[insert_at - 1].strip():
        insert_at -= 1

    new_line = f"{_indent(indent_level)}{key}: {formatted}\n"
    lines.insert(insert_at, new_line)


def apply_yaml_updates_preserve_comments(config_path: Path, updates: Iterable[YamlUpdate]) -> None:
    """Apply scalar updates to a YAML file while preserving comments.

    This is intended for user-editable config files that contain helpful
    comments we don't want to destroy.
    """
    if config_path.exists():
        lines = config_path.read_text(encoding="utf-8").splitlines(keepends=True)
    else:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        lines = []

    if not lines:
        lines = ["# Strawberry AI Spoke Configuration\n", "\n"]

    for upd in updates:
        if not upd.path:
            continue

        parent_start = 0
        parent_end = len(lines)

        for depth, key in enumerate(upd.path[:-1]):
            idx = _find_block(
                lines,
                key=key,
                indent_level=depth,
                start_idx=parent_start,
                end_idx=parent_end,
            )
            if idx is None:
                insert_at = parent_end
                while insert_at > parent_start and not lines[insert_at - 1].strip():
                    insert_at -= 1
                lines.insert(insert_at, f"{_indent(depth)}{key}:\n")
                idx = insert_at

            block_end = _find_block_end(lines, indent_level=depth, start_idx=idx)
            parent_start = idx + 1
            parent_end = block_end

        leaf_key = upd.path[-1]
        _set_scalar_in_block(
            lines,
            key=leaf_key,
            value=upd.value,
            indent_level=len(upd.path) - 1,
            start_idx=parent_start,
            end_idx=parent_end,
        )

    text = "".join(lines)
    if not text.endswith("\n"):
        text += "\n"

    config_path.write_text(text, encoding="utf-8")

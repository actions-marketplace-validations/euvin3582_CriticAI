"""Intelligent diff truncation for oversized PRs.

When a PR diff exceeds the model's context window, this module decides
which files to keep and which to drop. The strategy prioritizes
reviewable, hand-written code over auto-generated or low-signal files.

Priority tiers (lowest priority = dropped first):
  1. *.Designer.cs files (EF Core model snapshots — massive, auto-generated)
  2. Lock files (package-lock.json, yarn.lock, Cargo.lock, etc.)
  3. Migration files that are NOT Designer files (still auto-generated but
     may contain hand-written SQL worth reviewing)
  4. Large generated files (> 500 lines in the diff for a single file)
  5. Everything else (hand-written code — highest priority, kept last)
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# Patterns for low-priority files, ordered from lowest to highest priority
_LOW_PRIORITY_PATTERNS: list[tuple[str, int]] = [
    # Priority 0: EF Core Designer files (massive auto-generated snapshots)
    (r"\.Designer\.cs$", 0),
    # Priority 1: Lock files
    (r"(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|Cargo\.lock|Gemfile\.lock|poetry\.lock|composer\.lock)$", 1),
    # Priority 2: Migration files (but not Designer — those are priority 0)
    (r"[Mm]igrations?/.*\.(cs|sql)$", 2),
    # Priority 3: Auto-generated / vendored
    (r"(\.generated\.|\.g\.cs|\.pb\.go|__generated__|vendor/)", 3),
]

# Compiled patterns
_COMPILED_PATTERNS = [(re.compile(p), prio) for p, prio in _LOW_PRIORITY_PATTERNS]


@dataclass
class FileDiff:
    """A single file's portion of the unified diff."""

    path: str
    content: str  # full diff text for this file (from "diff --git" to next file)
    char_count: int
    priority: int  # higher = more important to keep


def truncate_diff(diff: str, max_chars: int) -> str:
    """Truncate a unified diff to fit within max_chars.

    If the diff is already under the limit, returns it unchanged.
    Otherwise, drops files starting from the lowest priority until
    the total fits. Appends a notice listing which files were dropped.

    Args:
        diff: The full unified diff text.
        max_chars: Maximum character count allowed. 0 = no limit.

    Returns:
        The (possibly truncated) diff, with a trailing notice if files
        were dropped.
    """
    if max_chars <= 0 or len(diff) <= max_chars:
        return diff

    # Split diff into per-file chunks
    file_diffs = _split_into_files(diff)

    if not file_diffs:
        return diff

    total_chars = sum(fd.char_count for fd in file_diffs)
    print(f"Diff size: {total_chars:,} chars exceeds limit of {max_chars:,} chars.")
    print(f"  Total files in diff: {len(file_diffs)}")

    # Sort by priority (ascending) so we drop lowest priority first
    sorted_diffs = sorted(file_diffs, key=lambda fd: fd.priority)

    # Drop files from the front (lowest priority) until we fit
    dropped: list[FileDiff] = []
    remaining_chars = total_chars

    for fd in sorted_diffs:
        if remaining_chars <= max_chars:
            break
        dropped.append(fd)
        remaining_chars -= fd.char_count

    if not dropped:
        return diff

    # Build the truncated diff — keep only non-dropped files in original order
    dropped_paths = {fd.path for fd in dropped}
    kept = [fd for fd in file_diffs if fd.path not in dropped_paths]

    print(f"  Truncation: keeping {len(kept)} files, dropping {len(dropped)} files.")
    for fd in dropped:
        print(f"    Dropped (priority {fd.priority}): {fd.path} ({fd.char_count:,} chars)")

    # Reassemble
    parts = [fd.content for fd in kept]

    # Append a notice so the model knows about the truncation
    notice = _build_truncation_notice(dropped)
    parts.append(notice)

    return "\n".join(parts)


def _split_into_files(diff: str) -> list[FileDiff]:
    """Split a unified diff into per-file chunks."""
    file_diffs: list[FileDiff] = []
    current_lines: list[str] = []
    current_path: str | None = None

    for line in diff.splitlines():
        if line.startswith("diff --git"):
            # Flush previous file
            if current_path is not None and current_lines:
                content = "\n".join(current_lines)
                file_diffs.append(FileDiff(
                    path=current_path,
                    content=content,
                    char_count=len(content),
                    priority=_get_priority(current_path, len(current_lines)),
                ))

            # Start new file
            match = re.search(r"diff --git a/(.*?) b/", line)
            current_path = match.group(1) if match else None
            current_lines = [line]
        else:
            current_lines.append(line)

    # Flush last file
    if current_path is not None and current_lines:
        content = "\n".join(current_lines)
        file_diffs.append(FileDiff(
            path=current_path,
            content=content,
            char_count=len(content),
            priority=_get_priority(current_path, len(current_lines)),
        ))

    return file_diffs


def _get_priority(path: str, line_count: int) -> int:
    """Determine the priority of a file (higher = more important to keep).

    Returns a value from 0 (lowest, drop first) to 10 (highest, keep).
    """
    # Check against known low-priority patterns
    for pattern, prio in _COMPILED_PATTERNS:
        if pattern.search(path):
            return prio

    # Large files (> 500 diff lines) that didn't match any pattern
    # are slightly lower priority than normal files
    if line_count > 500:
        return 7

    # Normal hand-written code — highest priority
    return 10


def _build_truncation_notice(dropped: list[FileDiff]) -> str:
    """Build a notice to append to the diff explaining what was truncated."""
    total_dropped_chars = sum(fd.char_count for fd in dropped)

    # Group dropped files by reason
    groups: dict[str, list[str]] = {}
    for fd in dropped:
        if fd.priority == 0:
            reason = "auto-generated EF Core Designer files"
        elif fd.priority == 1:
            reason = "lock files"
        elif fd.priority == 2:
            reason = "migration files"
        elif fd.priority == 3:
            reason = "generated/vendored files"
        elif fd.priority == 7:
            reason = "large files (>500 diff lines)"
        else:
            reason = "other files (to fit context limit)"
        groups.setdefault(reason, []).append(fd.path)

    lines = [
        "",
        "---",
        "NOTE: This diff was truncated to fit the model's context window.",
        f"  {len(dropped)} file(s) omitted ({total_dropped_chars:,} characters).",
        "  Omitted files by category:",
    ]

    for reason, paths in groups.items():
        lines.append(f"    - {reason} ({len(paths)} files):")
        # Show up to 5 file names per category
        for p in paths[:5]:
            lines.append(f"        {p}")
        if len(paths) > 5:
            lines.append(f"        ... and {len(paths) - 5} more")

    lines.append("")
    lines.append(
        "  Focus your review on the files included above. If any omitted "
        "file is critical to understanding the change, note that in your review."
    )
    lines.append("---")

    return "\n".join(lines)

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCAL_PATTERN_FILE = ".sensitive-patterns.local.txt"


@dataclass(frozen=True, slots=True)
class SensitivePattern:
    label: str
    regex: re.Pattern[str]
    source: str


@dataclass(frozen=True, slots=True)
class SensitiveFinding:
    source: str
    line_number: int
    label: str
    line_text: str


def _builtin_pattern(label: str, expression: str) -> SensitivePattern:
    return SensitivePattern(
        label=label,
        regex=re.compile(expression, re.IGNORECASE),
        source="builtin",
    )


BUILTIN_PATTERNS = (
    _builtin_pattern(
        "Forward plus-alias email address",
        r"\b[A-Za-z0-9._%+-]+\+[A-Za-z0-9._%+-]+@forwardnetworks\.com\b",
    ),
    _builtin_pattern(
        "Forward network identifier",
        r"\bnetwork(?:[ _-]?id)?\b[\"']?\s*[:=]?\s*[\"']?\d{5,}\b",
    ),
    _builtin_pattern(
        "Forward snapshot identifier",
        r"\bsnapshot(?:[ _-]?id)?\b[\"']?\s*[:=]?\s*[\"']?\d{5,}\b",
    ),
)


def _load_local_patterns(repo_root: Path) -> tuple[SensitivePattern, ...]:
    local_patterns_path = repo_root / LOCAL_PATTERN_FILE
    if not local_patterns_path.exists():
        return ()

    patterns: list[SensitivePattern] = []
    for line_number, raw_line in enumerate(
        local_patterns_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        value = raw_line.strip()
        if not value or value.startswith("#"):
            continue
        if value.startswith("re:"):
            pattern_text = value[3:].strip()
            label = f"local regex pattern line {line_number}"
        else:
            pattern_text = re.escape(value)
            label = f"local literal pattern line {line_number}"
        patterns.append(
            SensitivePattern(
                label=label,
                regex=re.compile(pattern_text, re.IGNORECASE),
                source=str(local_patterns_path.relative_to(repo_root)),
            )
        )
    return tuple(patterns)


def load_sensitive_patterns(repo_root: Path) -> tuple[SensitivePattern, ...]:
    return (*BUILTIN_PATTERNS, *_load_local_patterns(repo_root))


def _scan_text(
    text: str,
    *,
    source: str,
    patterns: tuple[SensitivePattern, ...],
) -> list[SensitiveFinding]:
    findings: list[SensitiveFinding] = []
    for line_number, line_text in enumerate(text.splitlines(), start=1):
        for pattern in patterns:
            if pattern.regex.search(line_text):
                findings.append(
                    SensitiveFinding(
                        source=source,
                        line_number=line_number,
                        label=pattern.label,
                        line_text=line_text.strip(),
                    )
                )
    return findings


def _scan_file(
    path: Path,
    *,
    repo_root: Path,
    patterns: tuple[SensitivePattern, ...],
) -> list[SensitiveFinding]:
    data = path.read_bytes()
    if b"\x00" in data:
        return []
    return _scan_text(
        data.decode("utf-8", errors="replace"),
        source=str(path.relative_to(repo_root)),
        patterns=patterns,
    )


def _tracked_files(repo_root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        cwd=repo_root,
        capture_output=True,
    )
    return [repo_root / Path(item.decode("utf-8")) for item in result.stdout.split(b"\x00") if item]


def _iter_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(nested for nested in sorted(path.rglob("*")) if nested.is_file())
            continue
        if path.is_file():
            files.append(path)
    return files


def _scan_paths(
    paths: list[Path],
    *,
    repo_root: Path,
    patterns: tuple[SensitivePattern, ...],
) -> list[SensitiveFinding]:
    findings: list[SensitiveFinding] = []
    seen: set[Path] = set()
    for path in _iter_files(paths):
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        findings.extend(_scan_file(resolved, repo_root=repo_root, patterns=patterns))
    return findings


def _scan_commit_history(
    *,
    repo_root: Path,
    patterns: tuple[SensitivePattern, ...],
    rev_args: list[str] | None = None,
) -> list[SensitiveFinding]:
    try:
        revisions = subprocess.run(
            ["git", "rev-list", *(rev_args or ["--all"])],
            check=True,
            cwd=repo_root,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    except subprocess.CalledProcessError:
        return []

    findings: list[SensitiveFinding] = []
    for revision in revisions:
        commit_message = subprocess.run(
            ["git", "show", "-s", "--format=%B", revision],
            check=True,
            cwd=repo_root,
            capture_output=True,
            text=True,
        ).stdout
        findings.extend(
            _scan_text(
                commit_message,
                source=f"commit:{revision[:12]}",
                patterns=patterns,
            )
        )
    return findings


def _format_finding(finding: SensitiveFinding) -> str:
    line_text = finding.line_text
    if len(line_text) > 160:
        line_text = f"{line_text[:157]}..."
    return f"{finding.source}:{finding.line_number}: {finding.label}: {line_text}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Block customer-derived identifiers from repo content and commit messages."
    )
    parser.add_argument("paths", nargs="*", help="Files or directories to scan.")
    parser.add_argument(
        "--git-files",
        action="store_true",
        help="Scan all tracked files in the current git repository.",
    )
    parser.add_argument(
        "--all-history",
        action="store_true",
        help="Scan every reachable commit message in the current git repository.",
    )
    parser.add_argument(
        "--rev-list",
        action="append",
        default=[],
        help="Additional git rev-list argument or revision range to scan.",
    )
    parser.add_argument(
        "--commit-msg-file",
        type=Path,
        help="Scan the provided commit message file.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    patterns = load_sensitive_patterns(REPO_ROOT)
    findings: list[SensitiveFinding] = []

    explicit_mode = any(
        [
            args.git_files,
            args.all_history,
            args.rev_list,
            args.commit_msg_file is not None,
            bool(args.paths),
        ]
    )

    if args.commit_msg_file is not None:
        findings.extend(
            _scan_file(
                args.commit_msg_file.resolve(),
                repo_root=args.commit_msg_file.resolve().parent,
                patterns=patterns,
            )
        )

    if args.all_history:
        findings.extend(_scan_commit_history(repo_root=REPO_ROOT, patterns=patterns))

    for rev_arg in args.rev_list:
        findings.extend(
            _scan_commit_history(
                repo_root=REPO_ROOT,
                patterns=patterns,
                rev_args=[rev_arg],
            )
        )

    if args.git_files:
        findings.extend(
            _scan_paths(_tracked_files(REPO_ROOT), repo_root=REPO_ROOT, patterns=patterns)
        )

    if args.paths:
        findings.extend(
            _scan_paths(
                [Path(path).resolve() for path in args.paths],
                repo_root=REPO_ROOT,
                patterns=patterns,
            )
        )

    if not explicit_mode:
        findings.extend(
            _scan_paths(_tracked_files(REPO_ROOT), repo_root=REPO_ROOT, patterns=patterns)
        )

    if not findings:
        return 0

    print("Sensitive content guard failed:")
    for finding in findings:
        print(_format_finding(finding))
    print(
        "Add local customer names to .sensitive-patterns.local.txt "
        "(literal lines or re:<regex>) so they are blocked before commit."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())

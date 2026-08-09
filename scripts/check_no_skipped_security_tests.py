"""Fail the release gate when a security test is explicitly disabled."""

from __future__ import annotations

import re
import sys
from pathlib import Path


SKIP_MARKERS = (
    re.compile(r"\bpytest\.(?:mark\.(?:skip(?:if)?|xfail)|skip|xfail)\b"),
    re.compile(r"\bunittest\.(?:skip(?:If|Unless)?|expectedFailure)\b"),
    re.compile(r"\b(?:describe|it|test)\.(?:skip|fixme|todo)\s*\("),
    re.compile(r"#\s*\[ignore(?:\s*=|\s*\()"),
    re.compile(r"#\s*\[ignore\s*\]"),
)

TEST_ROOTS = (
    Path("tests"),
    Path("frontend/test"),
    Path("frontend/e2e"),
    Path("frontend/src-wasm/src"),
)

TEST_SUFFIXES = {".py", ".js", ".jsx", ".rs"}


def find_skip_markers() -> list[str]:
    findings: list[str] = []
    for root in TEST_ROOTS:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in TEST_SUFFIXES:
                continue
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if any(pattern.search(line) for pattern in SKIP_MARKERS):
                    findings.append(f"{path}:{line_number}: {line.strip()}")
    return findings


def main() -> int:
    findings = find_skip_markers()
    if not findings:
        print("No explicitly skipped security tests found.")
        return 0

    print("Release blocked: explicitly skipped security tests found:", file=sys.stderr)
    for finding in findings:
        print(f"- {finding}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

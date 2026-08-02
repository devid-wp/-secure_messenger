from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOTS = (PROJECT_ROOT / "app", PROJECT_ROOT / "scripts")
TEXT_ROOTS = (
    PROJECT_ROOT / "frontend" / "src",
    PROJECT_ROOT / "frontend" / "src-tauri" / "src",
)
SENSITIVE_IDENTIFIERS = {
    "access_token",
    "refresh_token",
    "token",
    "password",
    "master_key",
    "private_key",
    "secret",
}
PYTHON_LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}
RUST_LOG_CALL = re.compile(
    r"(?:println|eprintln|log::\w+|tracing::\w+)!\s*\((.*?)\)\s*;",
    re.DOTALL,
)
JAVASCRIPT_LOG_CALL = re.compile(r"console\.\w+\s*\((.*?)\)\s*;", re.DOTALL)


def _is_sensitive(identifier: str) -> bool:
    lowered = identifier.lower()
    return any(
        lowered == sensitive or lowered.endswith(f"_{sensitive}")
        for sensitive in SENSITIVE_IDENTIFIERS
    )


def _python_log_calls(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "print":
            calls.append(node)
        elif (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in PYTHON_LOG_METHODS
        ):
            calls.append(node)
    return calls


class SecretLoggingPolicyTests(unittest.TestCase):
    def test_python_logs_do_not_reference_secret_values(self):
        violations: list[str] = []
        for root in PYTHON_ROOTS:
            for path in root.rglob("*.py"):
                if "__pycache__" in path.parts:
                    continue
                for call in _python_log_calls(path):
                    names = {
                        node.id for node in ast.walk(call) if isinstance(node, ast.Name)
                    }
                    exposed = sorted(name for name in names if _is_sensitive(name))
                    if exposed:
                        relative = path.relative_to(PROJECT_ROOT)
                        violations.append(f"{relative}:{call.lineno}: {', '.join(exposed)}")
        self.assertEqual([], violations, "secret value referenced by a log call")

    def test_rust_and_javascript_logs_do_not_reference_secret_values(self):
        violations: list[str] = []
        for root in TEXT_ROOTS:
            for path in root.rglob("*"):
                if path.suffix not in {".rs", ".js", ".jsx", ".ts", ".tsx"}:
                    continue
                source = path.read_text(encoding="utf-8")
                pattern = RUST_LOG_CALL if path.suffix == ".rs" else JAVASCRIPT_LOG_CALL
                for call in pattern.finditer(source):
                    identifiers = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", call.group(1))
                    exposed = sorted({name for name in identifiers if _is_sensitive(name)})
                    if exposed:
                        line = source.count("\n", 0, call.start()) + 1
                        relative = path.relative_to(PROJECT_ROOT)
                        violations.append(f"{relative}:{line}: {', '.join(exposed)}")
        self.assertEqual([], violations, "secret value referenced by a log call")


if __name__ == "__main__":
    unittest.main()

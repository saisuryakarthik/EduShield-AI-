import ast
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPERATIONAL_ROOTS = (ROOT / "backend", ROOT / "frontend-flask")
TEMPLATE_ROOT = ROOT / "frontend-flask" / "templates"
EXCLUDED_DIRS = {"tests", "__pycache__", ".venv", "venv"}
PASSWORD_CALLS = {
    "hash_password",
    "generate_password_hash",
    "verify_password",
    "check_password_hash",
}
PASSWORD_NAMES = {"password", "passwd", "pwd", "secret", "api_key", "apikey"}
CREDENTIAL_DISPLAY_PATTERN = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\s*/\s*\S+"
)
CREDENTIAL_UI_MARKERS = ("test-credentials", "Development access")


def _operational_python_files():
    for root in OPERATIONAL_ROOTS:
        for path in root.rglob("*.py"):
            if any(part in EXCLUDED_DIRS for part in path.parts):
                continue
            yield path


def _literal_string(node):
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and bool(node.value)
    )


def _violations(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(
                func, "attr", ""
            )

            if name in PASSWORD_CALLS:
                for index, argument in enumerate(node.args):
                    if _literal_string(argument):
                        found.append(
                            (
                                node.lineno,
                                f"literal passed to {name} argument {index}",
                            )
                        )

        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = (
                node.targets
                if isinstance(node, ast.Assign)
                else [node.target]
            )
            value = node.value

            for target in targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id.lower() in PASSWORD_NAMES
                    and _literal_string(value)
                ):
                    found.append(
                        (
                            node.lineno,
                            f"literal assigned to {target.id}",
                        )
                    )

    return found


def _template_violations(path):
    found = []

    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if any(marker in line for marker in CREDENTIAL_UI_MARKERS):
            found.append((line_number, "credential display marker"))

        if CREDENTIAL_DISPLAY_PATTERN.search(line):
            found.append((line_number, "email/password display pattern"))

    return found


class NoHardcodedOperationalPasswordsTest(unittest.TestCase):
    def test_operational_code_has_no_hardcoded_credentials(self):
        violations = []

        for path in _operational_python_files():
            for line, reason in _violations(path):
                violations.append(
                    f"{path.relative_to(ROOT)}:{line}: {reason}"
                )

        self.assertEqual(
            [],
            violations,
            "Hardcoded operational credentials found:\n"
            + "\n".join(violations),
        )

    def test_templates_do_not_display_credentials(self):
        violations = []

        for path in TEMPLATE_ROOT.rglob("*.html"):
            for line, reason in _template_violations(path):
                violations.append(
                    f"{path.relative_to(ROOT)}:{line}: {reason}"
                )

        self.assertEqual(
            [],
            violations,
            "Credential displays found in templates:\n"
            + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()

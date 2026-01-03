from __future__ import annotations

import ast
from pathlib import Path


def _iter_imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if isinstance(alias.name, str) and alias.name:
                    modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if isinstance(node.module, str) and node.module:
                modules.add(node.module)
    return modules


def test_rules_and_use_cases_do_not_import_integration_implementations() -> None:
    """
    Guardrail: rules + use cases should depend on gateways/Protocols, not concrete integration modules.
    """

    repo_root = Path(__file__).resolve().parents[3]
    targets = [
        repo_root / "backend" / "alarm" / "rules",
        repo_root / "backend" / "alarm" / "use_cases",
    ]

    forbidden_prefixes = {
        # Concrete implementations (IO, managers, task wiring).
        "integrations_home_assistant",
        "integrations_zwavejs",
        "transports_mqtt",
    }

    allowed_prefixes = {
        # Gateways are the intended dependency boundary.
        "alarm.gateways",
        "alarm.state_machine.settings",
    }

    def _is_allowed(module: str) -> bool:
        return any(module == allowed or module.startswith(f"{allowed}.") for allowed in allowed_prefixes)

    def _is_forbidden(module: str) -> bool:
        if _is_allowed(module):
            return False
        return any(module == forbidden or module.startswith(f"{forbidden}.") for forbidden in forbidden_prefixes)

    violations: list[tuple[str, str]] = []
    for base in targets:
        for path in sorted(base.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for module in sorted(_iter_imported_modules(tree)):
                if _is_forbidden(module):
                    violations.append((str(path.relative_to(repo_root)), module))

    assert not violations, "Import violations:\n" + "\n".join(f"- {filepath}: {module}" for filepath, module in violations)

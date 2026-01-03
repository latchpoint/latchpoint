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


def test_state_machine_does_not_import_integration_implementations() -> None:
    """
    Guardrail: keep the alarm state machine (domain) independent from integration implementations.
    """

    repo_root = Path(__file__).resolve().parents[3]
    state_machine_dir = repo_root / "backend" / "alarm" / "state_machine"

    allowed_prefixes = {
        # Dispatch boundary is the only integration entrypoint allowed from the domain.
        "alarm.signals",
    }

    forbidden_prefixes = {
        # All integration implementations must not be pulled into the state machine.
        "integrations_home_assistant",
        "integrations_zwavejs.manager",
        "integrations_zwavejs",
        "transports_mqtt.manager",
        "transports_mqtt",
    }

    # Keep the explicit allowed-list above from being shadowed by broader forbidden prefixes.
    def _is_allowed(module: str) -> bool:
        return any(module == allowed or module.startswith(f"{allowed}.") for allowed in allowed_prefixes)

    def _is_forbidden(module: str) -> bool:
        if _is_allowed(module):
            return False
        return any(module == forbidden or module.startswith(f"{forbidden}.") for forbidden in forbidden_prefixes)

    violations: list[tuple[str, str]] = []
    for path in sorted(state_machine_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in sorted(_iter_imported_modules(tree)):
            if _is_forbidden(module):
                violations.append((str(path.relative_to(repo_root)), module))

    assert not violations, "State machine import violations:\n" + "\n".join(
        f"- {filepath}: {module}" for filepath, module in violations
    )

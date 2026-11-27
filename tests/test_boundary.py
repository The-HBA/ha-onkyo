"""The library must not import Home Assistant, nor anything of the integration around it."""

import ast
from pathlib import Path

import pytest

LIB = Path(__file__).parents[1] / "custom_components" / "onkyo_eiscp" / "lib"
FILES = sorted(LIB.rglob("*.py"))
LIBRARY_PACKAGE = "custom_components.onkyo_eiscp.lib"


def imported_modules(path: Path) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.append(node.module)
    return modules


def test_the_library_files_were_found() -> None:
    assert len(FILES) >= 10


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(LIB)))
def test_no_home_assistant_import(path: Path) -> None:
    for module in imported_modules(path):
        assert module.split(".")[0] != "homeassistant", f"{path.name} imports {module}"


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(LIB)))
def test_no_import_of_the_integration_outside_the_library(path: Path) -> None:
    for module in imported_modules(path):
        if module.startswith("custom_components"):
            assert module == LIBRARY_PACKAGE or module.startswith(LIBRARY_PACKAGE + "."), (
                f"{path.name} imports {module}"
            )


def test_the_boundary_check_catches_an_import(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("import homeassistant.core\nfrom custom_components.onkyo_eiscp import const\n")
    assert imported_modules(bad) == ["homeassistant.core", "custom_components.onkyo_eiscp"]

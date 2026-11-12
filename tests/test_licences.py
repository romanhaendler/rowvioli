"""Decision 38: every dependency of the core and of every extra has a row in docs/package.md."""
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parent.parent


def name(requirement):
    return re.match(r"[A-Za-z0-9._-]+", requirement).group().lower().replace("_", "-")


def test_every_dependency_has_a_row_in_the_dependency_table():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    wanted = {name(r) for r in project["dependencies"]}
    for extra in project.get("optional-dependencies", {}).values():
        wanted |= {name(r) for r in extra}
    table = (ROOT / "docs/package.md").read_text().split("## Dependencies")[1].split("\n## ")[0]
    rows = set(re.findall(r"^\| `([^`]+)` \|", table, re.M))
    assert wanted <= rows, f"no row in the dependency table of docs/package.md: {sorted(wanted - rows)}"

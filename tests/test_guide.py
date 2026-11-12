"""docs/connector-guide.md shows the package under tests/connector, so its example cannot rot: every code block whose
first line names a file of that package (`# rowvioli-testing/<path>`) holds lines of that file, in their order."""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_the_guides_example_is_the_test_connector():
    shown = {}
    for block in re.findall(r"```\w*\n(.*?)```", (ROOT / "docs/connector-guide.md").read_text(), re.S):
        first, *lines = block.splitlines()
        if m := re.fullmatch(r"# rowvioli-testing/(\S+)", first):
            shown[m[1]] = lines
    assert set(shown) == {"pyproject.toml", "src/rowvioli_testing/__init__.py"}
    for path, lines in shown.items():
        rest = iter((ROOT / "tests/connector" / path).read_text().splitlines())
        for line in lines:  # each shown line occurs in the file after the one before it
            assert any(line == have for have in rest), f"{path} has no line {line!r} (or not in this order)"

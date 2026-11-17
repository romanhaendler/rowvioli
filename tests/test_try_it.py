"""The README's "Try it in a minute" block is run as written, against the suite's target."""
import os
import re
import subprocess
from pathlib import Path

from conftest import ROWVIOLI

README = Path(__file__).parent.parent / "README.md"


def test_the_try_it_block_mirrors_and_shows_the_change(rv, servers, tmp_path):
    block = re.search(r"## Try it in a minute.*?```sh\n(.*?)```", README.read_text(), re.S)[1]
    db = rv.target_url.rsplit("/", 1)[1]
    lines = []
    for line in block.splitlines():
        if line.startswith(("docker run", "until docker", "pip install", "docker stop")):
            continue  # the suite's containers and the installed program stand in for the reader's own
        if line.startswith("export ROWVIOLI_TARGET_URL"):
            line = f"export ROWVIOLI_TARGET_URL={rv.target_url}"  # the suite's target instead of the fixed port
        lines.append(line.replace("docker exec rowvioli-try psql -U postgres",
                                  f"docker exec {servers['target']} psql -U postgres -d {db}"))
    env = {**os.environ, "PATH": f"{Path(ROWVIOLI).parent}:{os.environ['PATH']}"}
    r = subprocess.run(["bash", "-e", "-c", "\n".join(lines)], cwd=tmp_path, capture_output=True, text=True,
                       env=env, timeout=120)
    assert r.returncode == 0, r.stderr
    assert rv.target("select customer_no, city from raw_try.customers order by 1") == [
        ("1", "Cologne"), ("2", "Essen"), ("3", "Mainz"), ("4", "Essen")]
    assert "3 inserted, 0 updated" in r.stderr and "1 inserted, 1 updated" in r.stderr
    assert rv.target("select count(*) from raw_try.customers__history where customer_no = '1'") == [(2,)]

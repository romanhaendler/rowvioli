import stat


def test_key_new_writes_a_private_key_with_mode_600_and_a_public_key(rv):
    r = rv.run("key", "new")
    assert r.returncode == 0, r.stderr
    private, public = rv.dir / "worker.key", rv.dir / "worker.pub"
    assert stat.S_IMODE(private.stat().st_mode) == 0o600
    assert private.read_text().strip() and public.read_text().strip()
    assert private.read_text() != public.read_text()


def test_key_new_never_overwrites_an_existing_key(rv):
    assert rv.run("key", "new").returncode == 0
    before = (rv.dir / "worker.key").read_text()
    assert rv.run("key", "new").returncode != 0
    assert (rv.dir / "worker.key").read_text() == before


def test_key_new_twice_gives_different_pairs(rv):
    assert rv.run("key", "new").returncode == 0
    first = (rv.dir / "worker.pub").read_text()
    (rv.dir / "worker.key").unlink()
    (rv.dir / "worker.pub").unlink()
    assert rv.run("key", "new").returncode == 0
    assert (rv.dir / "worker.pub").read_text() != first


def test_version_prints_the_installed_version(rv):
    from importlib.metadata import version
    r = rv.run("--version")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == version("rowvioli")

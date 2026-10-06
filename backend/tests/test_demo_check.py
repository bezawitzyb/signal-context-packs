"""demo-check (Step 5.5): checks never stop each other, and never print what they compare. No network."""

from ctxpack import demo_check as dc


def test_a_broken_check_is_a_red_line_not_a_crash():
    def boom():
        raise ConnectionError("https://user:secret@example.com refused")

    c = dc.run_check("x", boom)
    assert c.ok is False and c.detail == "ConnectionError" and "secret" not in c.detail


def test_files_contain_finds_the_needle_without_returning_it(tmp_path, monkeypatch):
    monkeypatch.setattr(dc, "REPO_DIR", tmp_path)
    (tmp_path / "a.txt").write_text("nothing here")
    (tmp_path / "b.js").write_text("const k = 'NEEDLE-123';")
    assert dc._files_contain([tmp_path / "a.txt", tmp_path / "b.js"], b"NEEDLE-123") == ["b.js"]


def test_mirror_url_from_repo():
    assert dc.mirror_url("someone/signal-context-packs") == "https://someone.github.io/signal-context-packs/"

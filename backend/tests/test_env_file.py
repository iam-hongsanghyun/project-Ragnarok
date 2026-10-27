"""backend/.env loader + .env.example parity (WA1)."""
from __future__ import annotations

import os
import re
from pathlib import Path

from backend.env_file import load_env_file, parse_env_text

_BACKEND = Path(__file__).resolve().parents[1]
# Quoted upper-case RAGNAROK_* / CLIMATERISK_* literals that are not env settings.
_NOT_SETTINGS = {
    "RAGNAROK_SECRET_",  # prefix; documented via the concrete RAGNAROK_SECRET_<NAME> example
    "RAGNAROK_AUTOSTART_FAILED",  # stderr marker, not a setting
}


def test_parse_env_text_handles_comments_quotes_export() -> None:
    parsed = parse_env_text(
        "# c\n\nA=1\nexport B = two words \nC=\"q v\"\nD='s'\nbad line\n=x\nE=a=b\n"
    )
    assert parsed == {"A": "1", "B": "two words", "C": "q v", "D": "s", "E": "a=b"}


def test_load_env_file_sets_missing_and_keeps_existing(tmp_path, monkeypatch) -> None:
    f = tmp_path / ".env"
    f.write_text("WA1_NEW=file\nWA1_KEEP=file\n", encoding="utf-8")
    monkeypatch.delenv("WA1_NEW", raising=False)
    monkeypatch.setenv("WA1_KEEP", "shell")
    applied = load_env_file(f)
    try:
        assert applied == ["WA1_NEW"]
        assert os.environ["WA1_NEW"] == "file"
        assert os.environ["WA1_KEEP"] == "shell"
    finally:
        os.environ.pop("WA1_NEW", None)


def test_load_env_file_missing_file_is_noop(tmp_path) -> None:
    assert load_env_file(tmp_path / "absent.env") == []


def test_every_env_var_the_backend_reads_is_in_env_example() -> None:
    example = (_BACKEND / ".env.example").read_text(encoding="utf-8")
    documented = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", example, flags=re.MULTILINE))
    read: set[str] = set()
    for sub in ("app", "mcp", "physical_risk_worker"):
        for py in (_BACKEND / sub).rglob("*.py"):
            read |= set(re.findall(r"[\"']((?:RAGNAROK|CLIMATERISK)_[A-Z0-9_]+)[\"']", py.read_text(encoding="utf-8")))
    read -= _NOT_SETTINGS
    missing = sorted(read - documented)
    assert not missing, f"read by code but absent from backend/.env.example: {missing}"
    # The reverse: documented settings must be read somewhere (no dead knobs).
    dead = sorted(n for n in documented - read if n != "RAGNAROK_SECRET_EIA_KEY" and not n.startswith("RAGNAROK_SECRET_"))
    assert not dead, f"documented in backend/.env.example but never read: {dead}"

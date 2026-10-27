"""Consistency checks for the Claude Desktop connector (connector/, scripts/connector_manifest.py).

The manifest, the Node launcher and the MCP server each state some facts (the
port, the mcp_config env keys, the tool list). These tests keep them in step.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_MANIFEST = _REPO / "connector" / "manifest.json"
_LAUNCHER = _REPO / "connector" / "server" / "index.js"
_GENERATOR = _REPO / "scripts" / "connector_manifest.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("connector_manifest", _GENERATOR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _manifest() -> dict:
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))


def test_manifest_is_valid_json_with_required_fields() -> None:
    m = _manifest()
    for key in ("manifest_version", "name", "version", "description", "author", "server"):
        assert key in m, key
    assert m["server"]["type"] == "node"
    assert m["server"]["entry_point"] == "server/index.js"


def test_every_mcp_config_variable_is_a_declared_user_config_field() -> None:
    m = _manifest()
    declared = set(m["user_config"])
    for name, value in m["server"]["mcp_config"]["env"].items():
        match = re.fullmatch(r"\$\{user_config\.([a-z_]+)\}", value)
        assert match, f"{name} must come from user_config"
        assert match.group(1) in declared, name


def test_every_user_config_field_is_typed_and_described() -> None:
    for key, field in _manifest()["user_config"].items():
        assert field.get("type") in {"string", "number", "boolean", "directory", "file"}, key
        assert field.get("title") and field.get("description"), key
        assert "default" in field, key


def test_no_secret_is_in_the_manifest() -> None:
    text = _MANIFEST.read_text(encoding="utf-8").lower()
    assert "api_key" not in text and "secret" not in text and "token" not in text


def test_launcher_defaults_agree_with_the_manifest() -> None:
    js = _LAUNCHER.read_text(encoding="utf-8")
    m = _manifest()
    assert re.search(r"setting\('RAGNAROK_PORT', '(\d+)'\)", js).group(1) == str(m["user_config"]["backend_port"]["default"])
    assert re.search(r"setting\('RAGNAROK_SESSION_ID', '([^']+)'\)", js).group(1) == m["user_config"]["session_id"]["default"]
    assert re.search(r"setting\('RAGNAROK_MCP_AUTONOMY', '([^']+)'\)", js).group(1) == m["user_config"]["autonomy"]["default"]


def test_generated_tools_are_the_registry_tools() -> None:
    gen = _load_generator()
    from backend.mcp.server import mcp

    import asyncio

    registered = {t.name for t in asyncio.run(mcp.list_tools())}
    generated = [t["name"] for t in gen.registry_tools()]
    assert len(generated) == len(set(generated))
    assert set(generated) == registered
    assert len(generated) >= 80


def test_generator_stages_manifest_with_tools_and_instructions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gen = _load_generator()
    monkeypatch.setattr(sys, "argv", ["connector_manifest.py", str(_MANIFEST), str(tmp_path)])
    assert gen.main(sys.argv) == 0
    staged = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert len(staged["tools"]) >= 80
    assert all(t["name"] and t["description"] for t in staged["tools"])
    info = json.loads((tmp_path / "server" / "server_info.json").read_text(encoding="utf-8"))
    assert "PyPSA" in info["instructions"]


def test_default_session_is_the_web_apps_session() -> None:
    # The connector's default must match the session the web UI opens (serve/run use "default").
    assert _manifest()["user_config"]["session_id"]["default"] == "default"

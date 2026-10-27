"""Plugin contract v2 gaps closed in WA2: result-mapper-only plugins load."""
from __future__ import annotations

import json

from backend.app import plugins


def test_result_mapper_only_plugin_is_discovered(tmp_path) -> None:
    d = tmp_path / "acme-mapper"
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps({"id": "acme-mapper", "name": "acme"}))
    (d / "plugin.py").write_text(
        "def result_mapper_matches(names):\n    return 'ACME' in names\n"
        "def result_mapper_map(sheets, filename):\n    return {'model': {}, 'result': {}}\n"
    )
    found = plugins.discover(tmp_path)
    assert "acme-mapper" in found
    manifest = found["acme-mapper"].to_dict()
    assert manifest["hooks"]["resultMapper"] is True
    assert manifest["hooks"]["analyze"] is False
    assert manifest["multiRun"] is False and manifest["contractVersion"] == 1


def test_half_a_mapper_pair_is_still_rejected(tmp_path) -> None:
    d = tmp_path / "half"
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps({"id": "half"}))
    (d / "plugin.py").write_text("def result_mapper_matches(names):\n    return True\n")
    assert plugins.discover(tmp_path) == {}

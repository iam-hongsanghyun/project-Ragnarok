"""Third-party TAB-MODULE store — install, validate, enable, remove.

The point of the server-side store: a module is project content, so it must NOT
live in browser localStorage, where the build-id reset (every app update) and
the "Clear cache" button both wipe it. These tests pin the install contract and
the id gate that stops a module shadowing a core tab.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from backend.app import tab_modules

MANIFEST = {"id": "hello-tab", "label": "Hello", "hint": "hi", "description": "demo", "order": 130}
ENTRY = 'module.exports = { mount(el) { el.textContent = "hi"; } };'


@pytest.fixture(autouse=True)
def _modules_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "modules"
    monkeypatch.setattr(tab_modules, "TAB_MODULES_DIR", d)
    return d


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, body in files.items():
            zf.writestr(name, body)
    return buf.getvalue()


def _package(manifest: dict | None = None, prefix: str = "") -> bytes:
    return _zip({
        f"{prefix}{tab_modules.MANIFEST_NAME}": json.dumps(manifest or MANIFEST),
        f"{prefix}index.js": ENTRY,
    })


# ── install ─────────────────────────────────────────────────────────────────────

def test_install_from_zip_registers_a_usable_module() -> None:
    mod = tab_modules.install_from_zip(_package())
    assert mod["manifest"]["id"] == "hello-tab"
    assert mod["manifest"]["entry"] == "index.js"
    assert mod["enabled"] is True
    assert mod["files"]["index.js"] == ENTRY
    assert [m["manifest"]["id"] for m in tab_modules.list_modules()] == ["hello-tab"]


def test_install_accepts_a_nested_directory_inside_the_zip() -> None:
    mod = tab_modules.install_from_zip(_package(prefix="hello-tab/"))
    assert mod["manifest"]["id"] == "hello-tab"
    assert set(mod["files"]) == {tab_modules.MANIFEST_NAME, "index.js"}


def test_reinstalling_an_id_updates_in_place_and_keeps_enabled_state() -> None:
    tab_modules.install_from_zip(_package())
    tab_modules.set_enabled("hello-tab", False)
    updated = tab_modules.install_from_zip(_zip({
        tab_modules.MANIFEST_NAME: json.dumps({**MANIFEST, "label": "Hello v2"}),
        "index.js": ENTRY,
        "extra.js": "// new file",
    }))
    assert updated["manifest"]["label"] == "Hello v2"
    assert "extra.js" in updated["files"]
    # The user's show/hide choice is not reset by an update.
    assert updated["enabled"] is False
    assert len(tab_modules.list_modules()) == 1


def test_install_from_a_server_directory() -> None:
    src = Path(tab_modules.TAB_MODULES_DIR).parent / "src-module"
    src.mkdir(parents=True)
    (src / tab_modules.MANIFEST_NAME).write_text(json.dumps(MANIFEST))
    (src / "index.js").write_text(ENTRY)
    mod = tab_modules.install_from_path(src)
    assert mod["manifest"]["id"] == "hello-tab"
    assert tab_modules.get_module("hello-tab") is not None


# ── validation ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad_id", list(tab_modules.RESERVED_IDS)[:6])
def test_ids_that_shadow_a_builtin_tab_are_refused(bad_id: str) -> None:
    with pytest.raises(tab_modules.ModuleError, match="collides"):
        tab_modules.install_from_zip(_package({**MANIFEST, "id": bad_id}))


@pytest.mark.parametrize("bad_id", ["", "has space", "1leading-digit", "../escape"])
def test_unusable_ids_are_refused(bad_id: str) -> None:
    with pytest.raises(tab_modules.ModuleError):
        tab_modules.install_from_zip(_package({**MANIFEST, "id": bad_id}))


def test_missing_manifest_is_refused() -> None:
    with pytest.raises(tab_modules.ModuleError, match=tab_modules.MANIFEST_NAME):
        tab_modules.install_from_zip(_zip({"index.js": ENTRY}))


def test_missing_entry_file_is_refused() -> None:
    with pytest.raises(tab_modules.ModuleError, match="index.js"):
        tab_modules.install_from_zip(_zip({tab_modules.MANIFEST_NAME: json.dumps(MANIFEST)}))


def test_zip_slip_paths_are_refused() -> None:
    payload = _zip({
        tab_modules.MANIFEST_NAME: json.dumps(MANIFEST),
        "index.js": ENTRY,
        "../escape.js": "// outside the install dir",
    })
    with pytest.raises(tab_modules.ModuleError, match="unsafe path"):
        tab_modules.install_from_zip(payload)


def test_a_broken_module_on_disk_is_skipped_not_fatal() -> None:
    tab_modules.install_from_zip(_package())
    broken = tab_modules.TAB_MODULES_DIR / "broken"
    broken.mkdir()
    (broken / tab_modules.MANIFEST_NAME).write_text("{ not json")
    # Discovery must still return the good one.
    assert [m["manifest"]["id"] for m in tab_modules.list_modules()] == ["hello-tab"]


# ── enable / remove ─────────────────────────────────────────────────────────────

def test_enabled_flag_persists_server_side() -> None:
    tab_modules.install_from_zip(_package())
    tab_modules.set_enabled("hello-tab", False)
    assert tab_modules.get_module("hello-tab")["enabled"] is False
    # Survives a fresh read of the store (i.e. a reload / another browser).
    assert tab_modules.list_modules()[0]["enabled"] is False
    tab_modules.set_enabled("hello-tab", True)
    assert tab_modules.list_modules()[0]["enabled"] is True


def test_remove_deletes_the_package_and_its_state() -> None:
    tab_modules.install_from_zip(_package())
    tab_modules.set_enabled("hello-tab", False)
    assert tab_modules.remove_module("hello-tab") is True
    assert tab_modules.list_modules() == []
    # A later re-install starts enabled again (state was dropped, not stale).
    assert tab_modules.install_from_zip(_package())["enabled"] is True


def test_remove_is_false_for_an_unknown_id() -> None:
    assert tab_modules.remove_module("nope") is False


def test_remove_refuses_to_escape_the_install_dir() -> None:
    with pytest.raises(tab_modules.ModuleError):
        tab_modules.remove_module("../../etc")


def test_ordering_is_by_bar_position_then_id() -> None:
    tab_modules.install_from_zip(_package({**MANIFEST, "id": "zzz", "order": 150}))
    tab_modules.install_from_zip(_package({**MANIFEST, "id": "aaa", "order": 300}))
    tab_modules.install_from_zip(_package({**MANIFEST, "id": "mmm", "order": 150}))
    assert [m["manifest"]["id"] for m in tab_modules.list_modules()] == ["mmm", "zzz", "aaa"]


def test_absent_order_defaults_after_everything_builtin() -> None:
    mod = tab_modules.install_from_zip(_package({"id": "hello-tab", "label": "Hello"}))
    assert mod["manifest"]["order"] == tab_modules.DEFAULT_ORDER

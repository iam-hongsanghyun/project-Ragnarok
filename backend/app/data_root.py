"""Where Ragnarok keeps what it makes as it works — sessions, runs, the queue, journals, exports,
physical-risk results, import caches: ``RAGNAROK_DATA_DIR``, else ``backend/data`` in the checkout.

A host that runs Ragnarok for several projects (bridge, one instance per project) points each at
its project's own folder, so the code stays in one checkout and only the data is the project's.
What ships with the code — configuration, examples, installed plug-ins and modules — stays in the
checkout's ``backend/data``.
"""

from __future__ import annotations

import os
from pathlib import Path

CHECKOUT_DATA = Path(__file__).resolve().parents[1] / "data"


def data_root() -> Path:
    """The folder Ragnarok's working data goes in."""
    named = os.environ.get("RAGNAROK_DATA_DIR", "").strip()
    return Path(named).expanduser() if named else CHECKOUT_DATA

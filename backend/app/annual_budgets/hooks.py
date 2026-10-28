"""Annual-budgets module hooks (see :mod:`backend.app.module_hooks`)."""
from __future__ import annotations

from backend.app import module_hooks as mh

from . import extra_functionality

# Rolling horizon: each window's share of an e_sum budget (a no-op in a single-shot solve).
mh.register("constraints", "annual-budgets", lambda ctx: extra_functionality, module="annual-budgets", order=20)

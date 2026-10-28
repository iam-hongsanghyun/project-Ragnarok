"""Carbon-pricing module hooks (see :mod:`backend.app.module_hooks`)."""
from __future__ import annotations

from backend.app import module_hooks as mh

from . import extra_functionality

# price x emissions, added to the objective after PyPSA built it; a no-op without a price.
mh.register("constraints", "carbon-pricing", lambda ctx: extra_functionality, module="carbon-pricing", order=10)

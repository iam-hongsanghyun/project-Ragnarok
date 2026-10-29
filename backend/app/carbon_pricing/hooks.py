"""Carbon-pricing module hooks (see :mod:`backend.app.module_hooks`)."""
from __future__ import annotations

from functools import partial

from backend.app import module_hooks as mh

from . import extra_functionality

# price x emissions, added to the objective after PyPSA built it; a no-op without a price. The carrier
# factors are the run's one shared map (RunContext.emissions_factors), not a read of the module's own.
mh.register(
    "constraints", "carbon-pricing",
    lambda ctx: partial(extra_functionality, carrier_factors=ctx.emissions_factors),
    module="carbon-pricing", order=10,
)

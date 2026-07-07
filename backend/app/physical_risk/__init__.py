"""Native physical-climate-risk capability (Phase 0 scaffold).

A faithful port of the user's standalone ``climaterisk`` orchestration into
Ragnarok, wired to a deterministic STUB engine. The real CLIMADA compute will
later live in a separate conda worker (see :mod:`.engine` for the seam); this
package never imports ``climada`` and adds no geospatial dependencies.

The public JSON contract (shared with the frontend, matched field-for-field):

* :class:`~.entities.Asset`, :class:`~.entities.Portfolio`
* :class:`~.entities.Run`, :class:`~.entities.PhysicalRunOutput`
* :class:`~.entities.Peril`, :class:`~.entities.VulnerabilityClass`
"""
from __future__ import annotations

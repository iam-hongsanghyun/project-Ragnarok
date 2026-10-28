"""Power-to-X (P2X) use-case surface.

A thin layer over the core model — there is no separate engine. It supplies
(1) a technology data file, (2) templates that wire PyPSA components into the
session model through the ordinary fragment merge, (3) the RFNBO matching rules
(Delegated Regulation (EU) 2023/1184) as an ``extra_functionality`` fragment and
pre-solve checks, and (4) results read from the P2X angle (LCOH / LCOA / LCOM,
cost waterfall, compliance).

Modules:

* :mod:`.technologies`  loader for ``technologies.json`` and parameter overrides
* :mod:`.chains`        chain templates -> workbook fragment + registry row
* :mod:`.rfnbo`         RFNBO constraint (linopy), additionality / geography / Art. 4 checks
* :mod:`.results`       LCOH, LCOA, LCOM, waterfall, compliance from a stored run
"""

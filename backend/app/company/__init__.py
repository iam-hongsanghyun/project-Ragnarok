"""Company module: owner-tagged company views and what-ifs on top of the solved optimum.

PyPSA knows no owner. Where assets carry an owner tag (``options.ownerColumn``, default ``owner``) this module
reports per-company KPIs, the annual P&L statement and the NPV / IRR / payback / DSCR finance model, and runs
the asset-swap (repowering) and ESS business-case what-ifs. All are ``study`` hooks declared in :mod:`.hooks`.
"""

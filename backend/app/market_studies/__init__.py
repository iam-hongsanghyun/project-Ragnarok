"""Market-studies module: post-solve and rule-based market analyses that PyPSA does not provide.

Each study reads the solved optimum (or re-solves a copy of it) and reports a result block; none changes the
base solve. They are ``study`` hooks (and one ``replace_solve`` hook) declared in :mod:`.hooks`:

========================  =====================================  ==============================================
Study                     Option                                 Result key
========================  =====================================  ==============================================
Market simulation         ``marketSimConfig`` (+ ``strategic``)  replaces the solve (merit-order clearing)
Merchant / price-taker    ``merchantConfig``                     ``merchant``
Bid strategy              ``bidStrategyConfig``                  ``bidStrategy`` / ``optimalBid``
PPA valuation, explorer   ``ppaConfig``                          ``ppa`` / ``ppaExplorer``
Price formation           always                                 ``priceFormation``
LMP decomposition         ``lmpDecompositionConfig``             ``lmpDecomposition``
========================  =====================================  ==============================================
"""

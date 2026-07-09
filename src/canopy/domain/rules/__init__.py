"""The diagnostic rule set.

Individual rules live here as pure functions over ``SignalSeries``. The registry that
declares each rule's required signals and orchestrates skipping lives in
``canopy.domain.registry``.
"""

from canopy.domain.rules.correlation import coolant_load_correlation

__all__ = ["coolant_load_correlation"]

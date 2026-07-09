"""Canopy — vehicle-diagnostic domain logic exposed as agent tools.

Phase 0 ships only the layers *below and at* the seam: the normalizer contract
(`canopy.model`), the data-access protocol and a synthetic reader (`canopy.readers`),
and the diagnostic rules (`canopy.domain`). No LLM code lives in this package yet.
"""

__version__ = "0.1.0"

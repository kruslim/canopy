"""Data access — *below the seam*.

Every backing (synthetic now; OBD and CAN+DBC later) implements the ``SignalReader``
protocol and returns the normalized ``SignalSeries``. Code above the seam depends on the
protocol, never on a concrete reader.
"""

from canopy.readers.base import SignalReader, UnknownSignalError
from canopy.readers.synthetic import SyntheticReader

__all__ = ["SignalReader", "SyntheticReader", "UnknownSignalError"]

"""Domain logic — *below the seam*. Where automotive expertise lives.

Rules consume ``SignalSeries`` and emit ``Finding``s that always cite evidence. They assume
a timeseries and degrade gracefully when handed a point read.
"""

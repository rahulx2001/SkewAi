"""Backtest engine — recompute cluster→advisory lead times per pack.

Public surface for `make backtest` and the live_risk retriever.
"""

from src.backtest.engine import best_lead_time, run_backtest

__all__ = [
    "best_lead_time",
    "run_backtest",
]

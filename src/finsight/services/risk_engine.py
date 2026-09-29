from __future__ import annotations

import numpy as np

from finsight.domain.schemas import RiskMetrics


class RiskEngine:
    """
    Deterministic financial risk calculator.

    Important design rule:
    LLMs may explain these metrics, but they do NOT calculate them.
    This keeps numerical results reproducible and testable.
    """

    @staticmethod
    def analyze(
        prices: list[float],
        confidence: float = 0.95,
        trading_days: int = 252,
        risk_free_rate: float = 0.0,
    ) -> RiskMetrics:
        arr = np.asarray(prices, dtype=np.float64)

        if arr.ndim != 1 or len(arr) < 3:
            raise ValueError("at least 3 prices are required")
        if not np.all(np.isfinite(arr)):
            raise ValueError("prices contain NaN or infinity")
        if np.any(arr <= 0):
            raise ValueError("prices must be positive")

        returns = arr[1:] / arr[:-1] - 1.0

        cumulative_return = float(arr[-1] / arr[0] - 1.0)
        annualized_volatility = float(np.std(returns, ddof=1) * np.sqrt(trading_days))

        running_max = np.maximum.accumulate(arr)
        drawdowns = arr / running_max - 1.0
        max_drawdown = float(np.min(drawdowns))

        # Historical VaR is represented as a positive loss number.
        loss_returns = -returns
        var = float(np.quantile(loss_returns, confidence))
        tail_losses = loss_returns[loss_returns >= var]
        cvar = float(np.mean(tail_losses)) if len(tail_losses) else var

        annualized_return = float(np.mean(returns) * trading_days)
        if annualized_volatility > 0:
            sharpe = (annualized_return - risk_free_rate) / annualized_volatility
        else:
            sharpe = None

        return RiskMetrics(
            observations=len(arr),
            cumulative_return=cumulative_return,
            annualized_volatility=annualized_volatility,
            max_drawdown=max_drawdown,
            historical_var=max(var, 0.0),
            historical_cvar=max(cvar, 0.0),
            sharpe_ratio=float(sharpe) if sharpe is not None else None,
        )

"""Simulated order fills and P&L tracking for backtesting."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.core.sizing import kalshi_maker_fee, kelly_contracts


@dataclass
class BacktestBet:
    ticker: str
    side: str                   # 'yes' | 'no'
    contracts: int
    cost_per_contract: float    # price paid in dollars
    my_probability: float       # model's estimate at bet time
    ts_ms: int
    resolved: bool = False
    outcome: int | None = None  # 1=win, 0=loss, None=unresolved
    pnl: float = 0.0            # realized after settlement


class VirtualPortfolio:
    def __init__(
        self,
        starting_bankroll: float = 1000.0,
        kelly_fraction: float = 0.25,
        max_contracts: int = 100,
        taker_fee_mult: float = 0.07,
        maker_fee_mult: float = 0.0175,
    ) -> None:
        self._bankroll = starting_bankroll
        self._kelly_fraction = kelly_fraction
        self._max_contracts = max_contracts
        self._open: list[BacktestBet] = []
        self._closed: list[BacktestBet] = []
        self._equity_snapshots: list[float] = []

    def size_bet(
        self,
        my_prob: float,
        market_price: float,
        is_maker: bool = True,
    ) -> int:
        """Return contracts to buy using fee-adjusted Kelly. 0 if no edge."""
        return kelly_contracts(
            my_prob=my_prob,
            market_price=Decimal(str(market_price)),
            bankroll_dollars=Decimal(str(self._bankroll)),
            kelly_fraction=self._kelly_fraction,
            max_contracts=self._max_contracts,
            is_maker=is_maker,
        )

    def open_bet(
        self,
        ticker: str,
        side: str,
        contracts: int,
        fill_price: float,
        my_probability: float,
        ts_ms: int,
    ) -> BacktestBet:
        """Record a new open position. Deducts cost from bankroll."""
        self._bankroll -= contracts * fill_price
        bet = BacktestBet(
            ticker=ticker,
            side=side,
            contracts=contracts,
            cost_per_contract=fill_price,
            my_probability=my_probability,
            ts_ms=ts_ms,
        )
        self._open.append(bet)
        return bet

    def settle_bet(
        self,
        ticker: str,
        outcome: int,  # 1=yes_settled, 0=no_settled
    ) -> float:
        """Mark matching open bet as resolved. Returns realized P&L."""
        for bet in self._open:
            if bet.ticker == ticker and not bet.resolved:
                fee = float(
                    kalshi_maker_fee(
                        bet.contracts,
                        Decimal(str(bet.cost_per_contract)),
                    )
                )
                if outcome == 1:
                    gross = float(bet.contracts)
                    pnl = gross - bet.contracts * bet.cost_per_contract - fee
                else:
                    pnl = -(bet.contracts * bet.cost_per_contract)

                # bankroll: cost was deducted at open; add back cost + pnl
                self._bankroll += bet.contracts * bet.cost_per_contract + pnl
                bet.resolved = True
                bet.outcome = outcome
                bet.pnl = pnl
                self._open.remove(bet)
                self._closed.append(bet)
                self._equity_snapshots.append(self._bankroll)
                return pnl
        return 0.0

    @property
    def bankroll(self) -> float:
        return self._bankroll

    @property
    def open_bets(self) -> list[BacktestBet]:
        return list(self._open)

    @property
    def closed_bets(self) -> list[BacktestBet]:
        return list(self._closed)

    @property
    def equity_curve(self) -> list[float]:
        return list(self._equity_snapshots)

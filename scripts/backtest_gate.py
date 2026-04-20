"""Check if the latest backtest result clears the go-live gate.

Gate criteria:
  - BSS > 0
  - resolved_bets >= 50
  - pnl_z_score > 1.5

Usage: python scripts/backtest_gate.py --module scanner
Returns exit code 0 on pass, 1 on fail.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest gate check")
    parser.add_argument("--module", required=True, help="Module name (e.g. scanner)")
    args = parser.parse_args()

    results_path = Path(f"backtest_results/{args.module}/latest.json")
    if not results_path.exists():
        print(f"ERROR: No results found at {results_path}", file=sys.stderr)
        sys.exit(1)

    with results_path.open() as f:
        result = json.load(f)

    bss = result.get("brier_skill_score", 0.0)
    n = result.get("resolved_bets", 0)
    z = result.get("pnl_z_score", 0.0)

    passed = bss > 0 and n >= 50 and z > 1.5

    print(f"Module:        {args.module}")
    print(f"BSS:           {bss:.4f}  (need > 0)       {'PASS' if bss > 0 else 'FAIL'}")
    print(f"Resolved bets: {n}        (need >= 50)      {'PASS' if n >= 50 else 'FAIL'}")
    print(f"PnL Z-score:   {z:.4f}  (need > 1.5)      {'PASS' if z > 1.5 else 'FAIL'}")
    print()
    print("GATE:", "PASS — ready for live trading" if passed else "FAIL — not ready")

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

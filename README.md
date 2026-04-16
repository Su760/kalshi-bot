# Kalshi Trading Bot

Phase 0: RSA-PSS auth + REST client wrapper + project scaffold.

## Setup

```bash
cp .env.example .env
# Fill in KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH
mkdir -p secrets
# Place your PEM key at ./secrets/kalshi_demo.pem
make install
```

## Verify connectivity

```bash
make health
```

Expected output:

```
env=demo
base_url=https://demo-api.kalshi.co/trade-api/v2
clock_skew_ms=<measured integer>
balance_cents=<integer>
status=OK
```

## Development

```bash
make test-unit   # run signing unit tests
make lint        # ruff linting
make typecheck   # mypy strict on src/core + src/config
make format      # black + ruff autofix
```

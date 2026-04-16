from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

# Fee coefficients (see research dossier §2.2)
TAKER_FEE_MULT = 0.07
MAKER_FEE_MULT = 0.0175
INDEX_TAKER_FEE_MULT = 0.035  # S&P 500 (INX*), Nasdaq-100 (NASDAQ100*) only

# URLs
DEMO_REST_BASE = "https://demo-api.kalshi.co/trade-api/v2"
DEMO_WS_URL    = "wss://demo-api.kalshi.co/trade-api/ws/v2"
PROD_REST_BASE = "https://api.elections.kalshi.com/trade-api/v2"
PROD_WS_URL    = "wss://api.elections.kalshi.com/trade-api/ws/v2"

# Signing
SIGNING_PATH_PREFIX = "/trade-api/v2"
MAX_CLOCK_SKEW_MS   = 2000
SIGNING_HASH        = hashes.SHA256()
SIGNING_SALT_LENGTH = padding.PSS.DIGEST_LENGTH  # 32 bytes. NEVER MAX_LENGTH.

# Rate limit (client-side, below Basic tier cap of 20 rps read)
CLIENT_READ_RPS = 15

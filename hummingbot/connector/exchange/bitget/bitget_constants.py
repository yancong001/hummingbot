# A single source of truth for constant variables related to the exchange
from hummingbot.core.api_throttler.data_types import LinkedLimitWeightPair, RateLimit
from hummingbot.core.data_type.common import OrderType, PositionMode
from hummingbot.core.data_type.in_flight_order import OrderState

EXCHANGE_NAME = "bitget"
DEFAULT_DOMAIN = ""
HBOT_BROKER_ID = "hummingbot"
HBOT_ORDER_ID = "t-HBOT"
MAX_ID_LEN = 30
TRADING_FEES_SYMBOL_LIMIT = 10

REST_URL = "https://api.bitget.com"
REST_URL_AUTH = ""
WS_URL = "wss://ws.bitget.com/mix/v1/stream"
PUBLIC_WS_URL = "wss://ws.bitget.com/v2/ws/public"
PRIVATE_WS_URL = "wss://ws.bitget.com/v2/ws/private"
DEFAULT_TIME_IN_FORCE = "gtc"

LIMIT = "limit"
MARKET = "market"

PRODUCT_TYPE = "spot"

# REST Public API endpoint
SERVER_TIME_PATH_URL = "/api/v2/public/time"
SYMBOL_PATH_URL = "/api/v2/spot/public/symbols"
ORDER_BOOK_ENDPOINT = "/api/v2/spot/market/orderbook"
ORDER_CREATE_PATH_URL = "/api/v2/spot/trade/place-order"
ORDER_DELETE_PATH_URL = "/api/v2/spot/trade/cancel-order"
ORDER_DETAIL_PATH_URL = "/api/v2/spot/trade/orderInfo"
USER_BALANCES_PATH_URL = "/api/v2/spot/account/assets"
LATEST_SYMBOL_INFORMATION_ENDPOINT = "/api/v2/spot/market/fills"
QUERY_ACTIVE_ORDER_PATH_URL = "/api/v2/spot/trade/orderInfo"
USER_TRADE_RECORDS_PATH_URL = "/api/v2/spot/trade/fills"
TRADING_FEE_QUERY_PATH_URL = "/api/v2/spot/market/vip-fee-rate"

TRADES_ENDPOINT_NAME = "spot.trades"
ORDER_SNAPSHOT_ENDPOINT_NAME = "spot.order_book"
ORDERS_UPDATE_ENDPOINT_NAME = "spot.order_book_update"
USER_TRADES_ENDPOINT_NAME = "spot.usertrades"
USER_ORDERS_ENDPOINT_NAME = "spot.orders"
USER_BALANCE_ENDPOINT_NAME = "spot.balances"
PONG_CHANNEL_NAME = "spot.pong"

# Timeouts
MESSAGE_TIMEOUT = 30.0
PING_TIMEOUT = 20.0
API_CALL_TIMEOUT = 10.0
API_MAX_RETRIES = 4

# Intervals
# Only used when nothing is received from WS
SHORT_POLL_INTERVAL = 5.0
# 45 seconds should be fine since we get trades, orders and balances via WS
LONG_POLL_INTERVAL = 45.0
# One minute should be fine since we get trades, orders and balances via WS
UPDATE_ORDER_STATUS_INTERVAL = 60.0
# 10 minute interval to update trading rules, these would likely never change whilst running.
INTERVAL_TRADING_RULES = 600
# According to the documentation this has to be less than 30 seconds
SECONDS_TO_WAIT_TO_RECEIVE_MESSAGE = 20

PUBLIC_URL_POINTS_LIMIT_ID = "PublicPoints"
PRIVATE_URL_POINTS_LIMIT_ID = "PrivatePoints"  # includes place-orders
CANCEL_ORDERS_LIMITS_ID = "CancelOrders"
ORDER_DELETE_LIMIT_ID = "OrderDelete"
ORDER_STATUS_LIMIT_ID = "OrderStatus"

# Request error codes
RET_CODE_OK = "00000"
RET_CODE_PARAMS_ERROR = "40007"
RET_CODE_API_KEY_INVALID = "40006"
RET_CODE_AUTH_TIMESTAMP_ERROR = "40005"
RET_CODE_ORDER_NOT_EXISTS = "43025"
RET_CODE_API_KEY_EXPIRED = "40014"

# WebSocket Public Endpoints
WS_PING_REQUEST = "ping"
WS_PONG_RESPONSE = "pong"
WS_ORDER_BOOK_EVENTS_TOPIC = "books"
WS_TRADES_TOPIC = "trade"
WS_INSTRUMENTS_INFO_TOPIC = "tickers"
WS_AUTHENTICATE_USER_ENDPOINT_NAME = "login"
WS_SUBSCRIPTION_TRADES_ENDPOINT_NAME = "fill"
WS_SUBSCRIPTION_ORDERS_ENDPOINT_NAME = "orders"
WS_SUBSCRIPTION_WALLET_ENDPOINT_NAME = "account"

UNKNOWN_ORDER_MESSAGE = "43001"


# Order Statuses
ORDER_STATE = {
    "live": OrderState.OPEN,
    "filled": OrderState.FILLED,
    "full-fill": OrderState.FILLED,
    "partial-fill": OrderState.PARTIALLY_FILLED,
    "partially_filled": OrderState.PARTIALLY_FILLED,
    "canceled": OrderState.CANCELED,
    "cancelled": OrderState.CANCELED,
}

RATE_LIMITS = [
    RateLimit(
        limit_id=LATEST_SYMBOL_INFORMATION_ENDPOINT,
        limit=20,
        time_interval=1,
    ),
    RateLimit(
        limit_id=ORDER_BOOK_ENDPOINT,
        limit=20,
        time_interval=1,
    ),
    RateLimit(
        limit_id=SERVER_TIME_PATH_URL,
        limit=20,
        time_interval=1,
    ),
    RateLimit(
        limit_id=QUERY_ACTIVE_ORDER_PATH_URL,
        limit=20,
        time_interval=1,
    ),
    RateLimit(
        limit_id=USER_TRADE_RECORDS_PATH_URL,
        limit=20,
        time_interval=2,
    ),
    RateLimit(
        limit_id=USER_BALANCES_PATH_URL,
        limit=10,
        time_interval=1,
    ),
    RateLimit(
        limit_id=SYMBOL_PATH_URL,
        limit=20,
        time_interval=1,
    ),
    RateLimit(
        limit_id=ORDER_CREATE_PATH_URL,
        limit=20,
        time_interval=1,
    ),
    RateLimit(
        limit_id=ORDER_DELETE_PATH_URL,
        limit=10,
        time_interval=1,
    ),
    RateLimit(
        limit_id=ORDER_DETAIL_PATH_URL,
        limit=20,
        time_interval=1,
    ),
    RateLimit(
        limit_id=TRADING_FEE_QUERY_PATH_URL,
        limit=20,
        time_interval=1,
    ),

]

import asyncio
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from hummingbot.connector.exchange.bitget import bitget_constants as CONSTANTS, bitget_web_utils as web_utils
from hummingbot.core.data_type.common import TradeType
from hummingbot.core.data_type.order_book_message import OrderBookMessage, OrderBookMessageType
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.web_assistant.connections.data_types import RESTMethod, WSJSONRequest
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.core.web_assistant.ws_assistant import WSAssistant
from hummingbot.logger import HummingbotLogger

if TYPE_CHECKING:
    from hummingbot.connector.exchange.bitget.bitget_exchange import BitgetExchange


class BitgetAPIOrderBookDataSource(OrderBookTrackerDataSource):

    _logger: Optional[HummingbotLogger] = None

    def __init__(self,
                 trading_pairs: List[str],
                 connector: 'BitgetExchange',
                 api_factory: WebAssistantsFactory,
                 domain: str = CONSTANTS.DEFAULT_DOMAIN):
        super().__init__(trading_pairs)
        self._connector = connector
        self._api_factory = api_factory
        self._trading_pairs: List[str] = trading_pairs
        self._diff_messages_queue_key = "books"
        self._trade_messages_queue_key = "trade"
        self._funding_info_messages_queue_key = "ticker"
        self._message_queue: Dict[str, asyncio.Queue] = defaultdict(asyncio.Queue)
        self._pong_response_event = None

    async def get_last_traded_prices(self,
                                     trading_pairs: List[str],
                                     domain: Optional[str] = None) -> Dict[str, float]:
        return await self._connector.get_last_traded_prices(trading_pairs=trading_pairs)

    async def _order_book_snapshot(self, trading_pair: str) -> OrderBookMessage:
        snapshot_response: Dict[str, Any] = await self._request_order_book_snapshot(trading_pair)
        snapshot_data: Dict[str, Any] = snapshot_response["data"]
        update_id: int = int(snapshot_data["ts"])
        snapshot_timestamp: float = update_id * 1e-3

        order_book_message_content = {
            "trading_pair": trading_pair,
            "update_id": update_id,
            "bids": [(price, amount) for price, amount in snapshot_data.get("bids", [])],
            "asks": [(price, amount) for price, amount in snapshot_data.get("asks", [])],
        }

        snapshot_msg: OrderBookMessage = OrderBookMessage(
            OrderBookMessageType.SNAPSHOT,
            order_book_message_content,
            snapshot_timestamp)

        return snapshot_msg

    async def _request_order_book_snapshot(self, trading_pair: str) -> Dict[str, Any]:
        """
        Retrieves a copy of the full order book from the exchange, for a particular trading pair.

        :param trading_pair: the trading pair for which the order book will be retrieved

        :return: the response from the exchange (JSON dictionary)
        """
        symbol = await self._connector.exchange_symbol_associated_to_pair(trading_pair=trading_pair)
        params = {
            "symbol": symbol,
            "limit": "100",
        }

        rest_assistant = await self._api_factory.get_rest_assistant()
        data = await rest_assistant.execute_request(
            url=web_utils.public_rest_url(path_url=CONSTANTS.ORDER_BOOK_ENDPOINT),
            params=params,
            method=RESTMethod.GET,
            throttler_limit_id=CONSTANTS.ORDER_BOOK_ENDPOINT,
        )
        return data

    async def _parse_trade_message(self, raw_message: Dict[str, Any], message_queue: asyncio.Queue):
        data = raw_message.get("data", [])
        inst_id = raw_message["arg"]["instId"]
        trading_pair = await self._connector.trading_pair_associated_to_exchange_symbol(symbol=inst_id)

        for trade_data in data:
            ts_ms = int(trade_data["tradeId"])
            trade_type = float(TradeType.BUY.value) if trade_data["side"] == "buy" else float(TradeType.SELL.value)
            message_content = {
                "trade_id": ts_ms,
                "trading_pair": trading_pair,
                "trade_type": trade_type,
                "amount": trade_data["size"],
                "price": trade_data["price"],
            }
            trade_message = OrderBookMessage(
                message_type=OrderBookMessageType.TRADE,
                content=message_content,
                timestamp=ts_ms * 1e-3,
            )
            message_queue.put_nowait(trade_message)

    async def _parse_order_book_diff_message(self, raw_message: Dict[str, Any], message_queue: asyncio.Queue):
        data = raw_message.get("data", {})
        inst_id = raw_message["arg"]["instId"]
        trading_pair = await self._connector.trading_pair_associated_to_exchange_symbol(symbol=inst_id)

        for book in data:
            update_id = int(book["ts"])
            timestamp = update_id * 1e-3

            order_book_message_content = {
                "trading_pair": trading_pair,
                "update_id": update_id,
                "bids": book["bids"],
                "asks": book["asks"],
            }
            diff_message = OrderBookMessage(
                message_type=OrderBookMessageType.DIFF,
                content=order_book_message_content,
                timestamp=timestamp
            )

            message_queue.put_nowait(diff_message)
    async def _parse_order_book_snapshot_message(self, raw_message: Dict[str, Any], message_queue: asyncio.Queue):
        data = raw_message.get("data", {})
        inst_id = raw_message["arg"]["instId"]
        trading_pair = await self._connector.trading_pair_associated_to_exchange_symbol(symbol=inst_id)
        for book in data:
            update_id = int(book["ts"])
            timestamp = update_id * 1e-3

            order_book_message_content = {
                "trading_pair": trading_pair,
                "update_id": update_id,
                "bids": book["bids"],
                "asks": book["asks"],
            }
            snapshot_msg: OrderBookMessage = OrderBookMessage(
                message_type=OrderBookMessageType.SNAPSHOT,
                content=order_book_message_content,
                timestamp=timestamp
            )

            message_queue.put_nowait(snapshot_msg)
    async def _subscribe_channels(self, ws: WSAssistant):
        try:
            payloads = []

            symbols = ",".join([await self._connector.exchange_symbol_associated_to_pair(trading_pair=pair)
                                for pair in self._trading_pairs])
            for channel in [
                self._diff_messages_queue_key,
                self._trade_messages_queue_key,
                self._funding_info_messages_queue_key,
            ]:
                payloads.append({
                    "instType": CONSTANTS.PRODUCT_TYPE.upper(),
                    "channel": channel,
                    "instId": symbols
                })
            final_payload = {
                "op": "subscribe",
                "args": payloads,
            }

            subscribe_request = WSJSONRequest(payload=final_payload)
            await ws.send(subscribe_request)
            self.logger().info("Subscribed to public order book, trade and funding info channels...")
        except asyncio.CancelledError:
            raise
        except Exception:
            self.logger().exception("Unexpected error occurred subscribing to order book trading and delta streams...")
            raise

    def _channel_originating_message(self, event_message: Dict[str, Any]) -> str:
        channel = ""
        if event_message == CONSTANTS.WS_PONG_RESPONSE and self._pong_response_event:
            self._pong_response_event.set()
        elif "event" in event_message:
            if event_message["event"] == "error":
                raise IOError(f"Public channel subscription failed ({event_message})")
        elif "arg" in event_message:
            channel = event_message["arg"].get("channel")
            if channel == CONSTANTS.WS_ORDER_BOOK_EVENTS_TOPIC and event_message.get("action") == "snapshot":
                channel = self._snapshot_messages_queue_key

        return channel

    async def _connected_websocket_assistant(self) -> WSAssistant:
        ws: WSAssistant = await self._api_factory.get_ws_assistant()
        await ws.connect(ws_url=CONSTANTS.PUBLIC_WS_URL, ping_timeout=CONSTANTS.PING_TIMEOUT)
        return ws

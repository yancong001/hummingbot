import asyncio
from decimal import ROUND_DOWN, Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

from bidict import bidict

from hummingbot.connector.constants import s_decimal_NaN
from hummingbot.connector.exchange.bitget import (
    bitget_constants as CONSTANTS,
    bitget_utils as utils,
    bitget_web_utils as web_utils,
)
from hummingbot.connector.exchange.bitget.bitget_api_order_book_data_source import BitgetAPIOrderBookDataSource
from hummingbot.connector.exchange.bitget.bitget_api_user_stream_data_source import BitgetAPIUserStreamDataSource
from hummingbot.connector.exchange.bitget.bitget_auth import BitgetAuth
from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.connector.utils import combine_to_hb_trading_pair
from hummingbot.core.data_type.common import OrderType, PositionAction, PositionSide, TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderState, OrderUpdate, TradeUpdate
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.data_type.trade_fee import AddedToCostTradeFee, TokenAmount, TradeFeeBase
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.utils.estimate_fee import build_trade_fee
from hummingbot.core.web_assistant.connections.data_types import RESTMethod
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory

if TYPE_CHECKING:
    from hummingbot.client.config.config_helpers import ClientConfigAdapter


class BitgetExchange(ExchangePyBase):
    web_utils = web_utils

    def __init__(self,
                 client_config_map: "ClientConfigAdapter",
                 bitget_api_key: str,
                 bitget_passphrase: str,
                 bitget_secret_key: str,
                 trading_pairs: Optional[List[str]] = None,
                 trading_required: bool = True,
                 domain: str = CONSTANTS.DEFAULT_DOMAIN):
        self.bitget_api_key = bitget_api_key
        self.bitget_passphrase = bitget_passphrase
        self.bitget_secret_key = bitget_secret_key
        self._domain = domain
        self._trading_required = True
        self._trading_pairs = trading_pairs
        self._last_order_fill_ts_s: float = 0
        super().__init__(client_config_map=client_config_map)

    @property
    def authenticator(self):
        bitgetAuth = BitgetAuth(
            api_key=self.bitget_api_key,
            secret_key=self.bitget_secret_key,
            passphrase=self.bitget_passphrase,
            time_provider=self._time_synchronizer)

        return bitgetAuth

    @property
    def name(self) -> str:
        return "bitget"

    @property
    def rate_limits_rules(self):
        return CONSTANTS.RATE_LIMITS

    @property
    def domain(self):
        return self._domain

    @property
    def client_order_id_max_length(self):
        return CONSTANTS.MAX_ID_LEN

    @property
    def client_order_id_prefix(self):
        return ""

    @property
    def trading_rules_request_path(self):
        return CONSTANTS.SYMBOL_PATH_URL

    @property
    def trading_pairs_request_path(self):
        return CONSTANTS.SYMBOL_PATH_URL

    @property
    def check_network_request_path(self):
        return CONSTANTS.SERVER_TIME_PATH_URL

    @property
    def trading_pairs(self):
        return self._trading_pairs

    @property
    def is_cancel_request_in_exchange_synchronous(self) -> bool:
        return True

    @property
    def is_trading_required(self) -> bool:
        return self._trading_required

    def supported_order_types(self):
        return [OrderType.MARKET, OrderType.LIMIT, OrderType.LIMIT_MAKER]

    async def get_all_pairs_prices(self) -> List[Dict[str, str]]:
        pairs_prices = await self._api_get(path_url=CONSTANTS.SYMBOL_PATH_URL)
        return pairs_prices

    def _is_request_exception_related_to_time_synchronizer(self, request_exception: Exception):
        # API documentation does not clarify the error message for timestamp related problems
        return False

    def _is_order_not_found_during_status_update_error(self, status_update_exception: Exception) -> bool:
        # TODO: implement this method correctly for the connector
        # The default implementation was added when the functionality to detect not found orders was introduced in the
        # ExchangePyBase class. Also fix the unit test test_lost_order_removed_if_not_found_during_order_status_update
        # when replacing the dummy implementation
        return False

    def _is_order_not_found_during_cancelation_error(self, cancelation_exception: Exception) -> bool:
        # TODO: implement this method correctly for the connector
        # The default implementation was added when the functionality to detect not found orders was introduced in the
        # ExchangePyBase class. Also fix the unit test test_cancel_order_not_found_in_the_exchange when replacing the
        # dummy implementation
        return CONSTANTS.UNKNOWN_ORDER_MESSAGE in str(cancelation_exception)

    def _create_web_assistants_factory(self) -> WebAssistantsFactory:
        return web_utils.build_api_factory(
            throttler=self._throttler,
            time_synchronizer=self._time_synchronizer,
            auth=self._auth)

    def _create_order_book_data_source(self) -> OrderBookTrackerDataSource:
        return BitgetAPIOrderBookDataSource(
            trading_pairs=self._trading_pairs,
            connector=self,
            api_factory=self._web_assistants_factory,
            domain=self.domain,
        )

    def _create_user_stream_data_source(self) -> UserStreamTrackerDataSource:
        return BitgetAPIUserStreamDataSource(
            auth=self._auth,
            trading_pairs=self._trading_pairs,
            connector=self,
            api_factory=self._web_assistants_factory,
            domain=self.domain,
        )

    def _get_fee(self,
                 base_currency: str,
                 quote_currency: str,
                 order_type: OrderType,
                 order_side: TradeType,
                 amount: Decimal,
                 price: Decimal = s_decimal_NaN,
                 is_maker: Optional[bool] = None) -> AddedToCostTradeFee:

        is_maker = is_maker or (order_type is OrderType.LIMIT_MAKER)
        trading_pair = combine_to_hb_trading_pair(base=base_currency, quote=quote_currency)
        if trading_pair in self._trading_fees:
            fees_data = self._trading_fees[trading_pair]
            fee_value = Decimal(fees_data["makerFeeRate"]) if is_maker else Decimal(fees_data["takerFeeRate"])
            fee = AddedToCostTradeFee(percent=fee_value)
        else:
            fee = build_trade_fee(
                self.name,
                is_maker,
                base_currency=base_currency,
                quote_currency=quote_currency,
                order_type=order_type,
                order_side=order_side,
                amount=amount,
                price=price,
            )
        return fee

    def _initialize_trading_pair_symbols_from_exchange_info(self, exchange_info: Dict[str, Any]):
        mapping = bidict()
        for symbol_data in filter(utils.is_exchange_information_valid, exchange_info["data"]):
            mapping[symbol_data["symbol"]] = combine_to_hb_trading_pair(base=symbol_data["baseCoin"],
                                                                        quote=symbol_data["quoteCoin"])
        self._set_trading_pair_symbol_map(mapping)

    async def _initialize_trading_pair_symbol_map(self):
        # This has to be reimplemented because the request requires an extra parameter
        try:
            exchange_info = await self._api_get(
                path_url=self.trading_pairs_request_path
            )
            self._initialize_trading_pair_symbols_from_exchange_info(exchange_info=exchange_info)
        except Exception:
            self.logger().exception("There was an error requesting exchange info.")

    async def _update_trading_rules(self):
        exchange_info = await self._api_get(
            path_url=self.trading_rules_request_path
        )
        trading_rules_list = await self._format_trading_rules(exchange_info)
        self._trading_rules.clear()
        for trading_rule in trading_rules_list:
            self._trading_rules[trading_rule.trading_pair] = trading_rule
        self._initialize_trading_pair_symbols_from_exchange_info(exchange_info=exchange_info)

    async def _place_order(self,
                           order_id: str,
                           trading_pair: str,
                           amount: Decimal,
                           trade_type: TradeType,
                           order_type: OrderType,
                           price: Decimal,
                           **kwargs) -> Tuple[str, float]:
        path_url = CONSTANTS.ORDER_CREATE_PATH_URL
        side = trade_type.name.lower()
        order_type_str = "market" if order_type == OrderType.MARKET else "limit"
        data = {
            "size": str(amount),
            "clientOid": order_id,
            "side": side,
            "symbol": await self.exchange_symbol_associated_to_pair(trading_pair=trading_pair),
            "orderType": order_type_str,
        }
        if order_type.is_limit_type():
            data["price"] = str(price)
            data["force"] = CONSTANTS.DEFAULT_TIME_IN_FORCE
            if order_type is OrderType.LIMIT_MAKER:
                data["force"] = "post_only"
        else:
            data["force"] = "ioc"
            if trade_type.name.lower() == 'buy':
                if price.is_nan():
                    price = self.get_price_for_volume(
                        trading_pair,
                        True,
                        amount
                    ).result_price
                data.update({
                    "size": f"{price * amount:f}",
                })
        resp = await self._api_post(
            path_url=path_url,
            data=data,
            is_auth_required=True,
        )
        if resp["code"] != CONSTANTS.RET_CODE_OK:
            formatted_ret_code = self._format_ret_code_for_print(resp["code"])
            raise IOError(f"Error submitting order {order_id}: {formatted_ret_code} - {resp['msg']}")

        return str(resp["data"]["orderId"]), self.current_timestamp


    def _format_ret_code_for_print(ret_code: Union[str, int]) -> str:
        return f"ret_code <{ret_code}>"

    async def _place_cancel(self, order_id: str, tracked_order: InFlightOrder):
        """
        This implementation specific function is called by _cancel, and returns True if successful
        """

        data = {
            "symbol": await self.exchange_symbol_associated_to_pair(tracked_order.trading_pair),
            "orderId": tracked_order.exchange_order_id
        }

        cancel_result = await self._api_post(
            path_url=CONSTANTS.ORDER_DELETE_PATH_URL,
            is_auth_required=True,
            data=data
        )
        response_code = cancel_result["code"]

        if response_code != CONSTANTS.RET_CODE_OK:
            if response_code == CONSTANTS.RET_CODE_ORDER_NOT_EXISTS:
                await self._order_tracker.process_order_not_found(order_id)
            formatted_ret_code = self._format_ret_code_for_print(response_code)
            raise IOError(f"{formatted_ret_code} - {cancel_result['msg']}")

        return True

    async def _user_stream_event_listener(self):
        """
        Listens to message in _user_stream_tracker.user_stream queue.
        """
        async for event_message in self._iter_user_event_queue():
            try:
                if event_message != "pong":
                    data = event_message["arg"]
                    endpoint = data.get("channel", None)
                    payload = event_message["data"]

                    if endpoint is not None:
                        if endpoint == CONSTANTS.WS_SUBSCRIPTION_TRADES_ENDPOINT_NAME:
                            for trade_msg in payload:
                                self._process_trade_event_message(trade_msg)
                        elif endpoint == CONSTANTS.WS_SUBSCRIPTION_ORDERS_ENDPOINT_NAME:
                            for order_msg in payload:
                                # self._process_trade_event_message(order_msg)
                                self._process_order_event_message(order_msg)
                        elif endpoint == CONSTANTS.WS_SUBSCRIPTION_WALLET_ENDPOINT_NAME:
                            for wallet_msg in payload:
                                self._process_wallet_event_message(wallet_msg)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().exception("Unexpected error in user stream listener loop.")

    def _process_trade_event_message(self, trade_msg: Dict[str, Any]):
        """
        Updates in-flight order and trigger order filled event for trade message received. Triggers order completed
        event if the total executed amount equals to the specified order amount.

        :param trade_msg: The trade event message payload
        """

        exchange_order_id = str(trade_msg["orderId"])
        fillable_order = self._order_tracker.all_fillable_orders_by_exchange_order_id.get(exchange_order_id)


        if fillable_order is None:
            self.logger().debug(f"Ignoring trade message with order id {exchange_order_id}: not in in_flight_orders.")
        else:
            trade_update = self._parse_websocket_trade_update(trade_msg=trade_msg, tracked_order=fillable_order)
            if trade_update:
                self._order_tracker.process_trade_update(trade_update)


    def _process_order_event_message(self, order_msg: Dict[str, Any]):
        """
        Updates in-flight order and triggers cancellation or failure event if needed.

        :param order_msg: The order event message payload
        """
        order_status = CONSTANTS.ORDER_STATE[order_msg["status"]]
        client_order_id = str(order_msg["clientOid"])
        updatable_order = self._order_tracker.all_updatable_orders.get(client_order_id)
        if updatable_order is not None:
            new_order_update: OrderUpdate = OrderUpdate(
                trading_pair=updatable_order.trading_pair,
                update_timestamp=self.current_timestamp,
                new_state=order_status,
                client_order_id=client_order_id,
                exchange_order_id=order_msg["orderId"],
            )
            self._order_tracker.process_order_update(new_order_update)

    def _parse_websocket_trade_update(self, trade_msg: Dict, tracked_order: InFlightOrder) -> TradeUpdate:
        trade_id: str = trade_msg["tradeId"]
        if trade_id is not None:
            trade_id = str(trade_id)
            fee_detail = trade_msg["feeDetail"]
            fee_amount = 0
            fee_asset = ""
            if len(fee_detail) > 0:
                fee_asset = fee_detail[0]["feeCoin"]
                fee_amount = Decimal(fee_detail[0]["totalFee"])
            flat_fees = [] if fee_amount == Decimal("0") else [TokenAmount(amount=fee_amount, token=fee_asset)]

            fee = TradeFeeBase.new_spot_fee(
                fee_schema=self.trade_fee_schema(),
                percent_token=fee_asset,
                flat_fees=flat_fees,
                trade_type=tracked_order.trade_type,
            )

            exec_price = Decimal(trade_msg["priceAvg"])
            exec_time = int(trade_msg["uTime"]) * 1e-3

            trade_update: TradeUpdate = TradeUpdate(
                trade_id=trade_id,
                client_order_id=tracked_order.client_order_id,
                exchange_order_id=str(trade_msg["orderId"]),
                trading_pair=tracked_order.trading_pair,
                fill_timestamp=exec_time,
                fill_price=exec_price,
                fill_base_amount=Decimal(trade_msg["size"]),
                fill_quote_amount=exec_price * Decimal(trade_msg["size"]),
                fee=fee,
            )
            return trade_update

    def _process_wallet_event_message(self, wallet_msg: Dict[str, Any]):
        """
        Updates account balances.
        :param wallet_msg: The account balance update message payload
        """
        symbol = wallet_msg.get("coin", None)
        if symbol is not None:
            available = Decimal(str(wallet_msg["available"])) - Decimal(wallet_msg["frozen"])
            total = Decimal(str(wallet_msg["available"]))
            self._account_balances[symbol] = total
            self._account_available_balances[symbol] = available

    async def _update_balances(self):
        local_asset_names = set(self._account_balances.keys())
        remote_asset_names = set()

        response = await self._api_get(
            path_url=CONSTANTS.USER_BALANCES_PATH_URL,
            params={"assetType": "hold_only"},
            is_auth_required=True)
        if response:
            for balance_entry in response["data"]:
                asset_name = balance_entry["coin"]
                self._account_available_balances[asset_name] = Decimal(balance_entry["available"]) - Decimal(balance_entry["frozen"])
                self._account_balances[asset_name] = Decimal(balance_entry["available"])
                remote_asset_names.add(asset_name)

            asset_names_to_remove = local_asset_names.difference(remote_asset_names)
            for asset_name in asset_names_to_remove:
                del self._account_available_balances[asset_name]
                del self._account_balances[asset_name]

    async def _format_trading_rules(self, raw_trading_pair_info: Dict[str, Any]) -> List[TradingRule]:
        trading_rules = []

        for info in raw_trading_pair_info["data"]:
            if utils.is_pair_information_valid(info):
                try:
                    trading_pair = await self.trading_pair_associated_to_exchange_symbol(symbol=info.get("symbol"))
                    minTradeAmount = Decimal(info["minTradeAmount"])
                    min_price_inc = Decimal(f"1e-{info['pricePrecision']}")
                    min_amount_inc = Decimal(f"1e-{info['quantityPrecision']}")
                    if minTradeAmount == 0:
                        minTradeAmount = Decimal(f"1e-{info['quotePrecision']}")
                    trading_rules.append(
                        TradingRule(trading_pair=trading_pair,
                                    min_order_size=minTradeAmount,
                                    max_order_size=Decimal(info["maxTradeAmount"]),
                                    min_price_increment=min_price_inc,
                                    min_base_amount_increment=min_amount_inc,
                                    min_notional_size=Decimal(info["minTradeUSDT"]))
                    )
                except Exception:
                    self.logger().error(f"Error parsing the trading pair rule {info}. Skipping.", exc_info=True)
        return trading_rules

    async def _update_trading_fees(self):
        pass

    async def _all_trade_updates_for_order(self, order: InFlightOrder) -> List[TradeUpdate]:
        trade_updates = []

        if order.exchange_order_id is not None:
            try:
                all_fills_response = await self._request_order_fills(order=order)
                fills_data = all_fills_response.get("data", [])
                for fill_data in fills_data:
                    trade_update = self._parse_trade_update(trade_msg=fill_data, tracked_order=order)
                    trade_updates.append(trade_update)
            except IOError as ex:
                if not self._is_request_exception_related_to_time_synchronizer(request_exception=ex):
                    raise

        return trade_updates

    def _parse_trade_update(self, trade_msg: Dict, tracked_order: InFlightOrder) -> TradeUpdate:
        trade_id: str = str(trade_msg["tradeId"])
        fee_detail = trade_msg["feeDetail"]
        fee_amount = 0
        fee_asset = ""
        if len(fee_detail) > 0:
            fee_asset = fee_detail["feeCoin"]
            fee_amount = Decimal(fee_detail["totalFee"])
        flat_fees = [] if fee_amount == Decimal("0") else [TokenAmount(amount=fee_amount, token=fee_asset)]

        fee = TradeFeeBase.new_spot_fee(
            fee_schema=self.trade_fee_schema(),
            percent_token=fee_asset,
            flat_fees=flat_fees,
            trade_type=tracked_order.trade_type,
        )

        exec_price = Decimal(trade_msg["priceAvg"])
        exec_time = int(trade_msg["uTime"]) * 1e-3

        trade_update: TradeUpdate = TradeUpdate(
            trade_id=trade_id,
            client_order_id=tracked_order.client_order_id,
            exchange_order_id=str(trade_msg["orderId"]),
            trading_pair=tracked_order.trading_pair,
            fill_timestamp=exec_time,
            fill_price=exec_price,
            fill_base_amount=Decimal(trade_msg["size"]),
            fill_quote_amount=exec_price * Decimal(trade_msg["size"]),
            fee=fee,
        )

        return trade_update

    async def _request_order_fills(self, order: InFlightOrder) -> Dict[str, Any]:
        exchange_symbol = await self.exchange_symbol_associated_to_pair(order.trading_pair)
        body_params = {
            "orderId": order.exchange_order_id,
            "symbol": exchange_symbol,
        }
        res = await self._api_get(
            path_url=CONSTANTS.USER_TRADE_RECORDS_PATH_URL,
            params=body_params,
            is_auth_required=True,
        )
        return res

    async def _request_order_status(self, tracked_order: InFlightOrder) -> OrderUpdate:
        try:
            order_status_data = await self._request_order_status_data(tracked_order=tracked_order)
            order_msg = order_status_data["data"][0]
            client_order_id = str(order_msg["clientOid"])

            order_update: OrderUpdate = OrderUpdate(
                trading_pair=tracked_order.trading_pair,
                update_timestamp=self.current_timestamp,
                new_state=CONSTANTS.ORDER_STATE[order_msg["status"]],
                client_order_id=client_order_id,
                exchange_order_id=order_msg["orderId"],
            )

            return order_update

        except IOError as ex:
            if self._is_request_exception_related_to_time_synchronizer(request_exception=ex):
                order_update = OrderUpdate(
                    client_order_id=tracked_order.client_order_id,
                    trading_pair=tracked_order.trading_pair,
                    update_timestamp=self.current_timestamp,
                    new_state=tracked_order.current_state,
                )
            else:
                raise

        return order_update


    async def _request_order_status_data(self, tracked_order: InFlightOrder) -> Dict:
        exchange_symbol = await self.exchange_symbol_associated_to_pair(tracked_order.trading_pair)
        query_params = {
            "symbol": exchange_symbol,
            "clientOid": tracked_order.client_order_id
        }
        if tracked_order.exchange_order_id is not None:
            query_params["orderId"] = tracked_order.exchange_order_id

        resp = await self._api_get(
            path_url=CONSTANTS.QUERY_ACTIVE_ORDER_PATH_URL,
            params=query_params,
            is_auth_required=True,
        )

        return resp

    async def _get_last_traded_price(self, trading_pair: str) -> float:
        exchange_symbol = await self.exchange_symbol_associated_to_pair(trading_pair)
        params = {"symbol": exchange_symbol}
        resp_json = await self._api_get(
            path_url=CONSTANTS.LATEST_SYMBOL_INFORMATION_ENDPOINT,
            params=params,
        )
        price = float(resp_json["data"]["bestAsk"])
        return price

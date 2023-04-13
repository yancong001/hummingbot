import asyncio
import logging
from dataclasses import dataclass
from typing import List, Optional, Type
from decimal import Decimal

from hummingbot.client.config.trade_fee_schema_loader import TradeFeeSchemaLoader
from hummingbot.core.data_type.trade_fee import (
    TradeFeeSchema
)

from hummingbot.connector.utils import combine_to_hb_trading_pair, split_hb_trading_pair
from hummingbot.core.data_type.trade_fee import TokenAmount, TradeFeeBase
from hummingbot.core.event.events import OrderType, TradeType
from hummingbot.core.rate_oracle.rate_oracle import RateOracle
from hummingbot.core.utils.async_utils import safe_gather
# from hummingbot.core.utils.estimate_fee import build_trade_fee
from hummingbot.logger import HummingbotLogger
from hummingbot.strategy.market_trading_pair_tuple import MarketTradingPairTuple

s_decimal_nan = Decimal("NaN")
s_decimal_0 = Decimal("0")
arbprop_logger: Optional[HummingbotLogger] = None
S_DECIMAL_0 = Decimal(0)

@dataclass
class AmmTradeFeeBase(TradeFeeBase):

    def fee_amount_in_token(
            self,
            trading_pair: str,
            price: Decimal,
            order_amount: Decimal,
            token: str,
            exchange = None,
            rate_source = None,      # noqa: F821
            taker_to_maker_quote_conversion_rate = None,

    ) -> Decimal:
        base, quote = split_hb_trading_pair(trading_pair)
        fee_amount: Decimal = S_DECIMAL_0
        if self.percent != S_DECIMAL_0:
            amount_from_percentage: Decimal = (price * order_amount) * self.percent
            if self._are_tokens_interchangeable(quote, token):
                fee_amount += amount_from_percentage
            else:
                conversion_pair: str = combine_to_hb_trading_pair(base=quote, quote=token)
                if taker_to_maker_quote_conversion_rate:
                    conversion_rate: Decimal = taker_to_maker_quote_conversion_rate
                else:
                    conversion_rate: Decimal = self._get_exchange_rate(conversion_pair, exchange, rate_source)
                fee_amount += amount_from_percentage * conversion_rate
        for flat_fee in self.flat_fees:
            if self._are_tokens_interchangeable(flat_fee.token, token):
                # No need to convert the value
                fee_amount += flat_fee.amount
            elif (self._are_tokens_interchangeable(flat_fee.token, base)
                  and (self._are_tokens_interchangeable(quote, token))):
                # In this case instead of looking for the rate we use directly the price in the parameters
                fee_amount += flat_fee.amount * price
            else:
                conversion_pair: str = combine_to_hb_trading_pair(base=flat_fee.token, quote=token)
                # conversion_rate: Decimal = self._get_exchange_rate(conversion_pair, exchange, rate_source)
                if taker_to_maker_quote_conversion_rate:
                    conversion_rate: Decimal = taker_to_maker_quote_conversion_rate
                else:
                    conversion_rate: Decimal = self._get_exchange_rate(conversion_pair, exchange, rate_source)
                fee_amount += (flat_fee.amount * conversion_rate)
        return fee_amount

    @classmethod
    def new_spot_fee(cls,
                     fee_schema: TradeFeeSchema,
                     trade_type: TradeType,
                     percent: Decimal = S_DECIMAL_0,
                     percent_token: Optional[str] = None,
                     flat_fees: Optional[List[TokenAmount]] = None) -> "TradeFeeBase":
        fee_cls: Type[TradeFeeBase] = (
            AddedToCostTradeFee
            if (trade_type == TradeType.BUY and
                (not fee_schema.buy_percent_fee_deducted_from_returns
                 or fee_schema.percent_fee_token is not None))
            else DeductedFromReturnsTradeFee)
        return fee_cls(
            percent=percent,
            percent_token=percent_token,
            flat_fees=flat_fees or []
        )

class AddedToCostTradeFee(AmmTradeFeeBase):

    @classmethod
    def type_descriptor_for_json(cls) -> str:
        return "AddedToCost"

    def get_fee_impact_on_order_cost(
            self, order_candidate: "OrderCandidate", exchange: "ExchangeBase"
    ) -> Optional[TokenAmount]:
        """
        WARNING: Do not use this method for sizing. Instead, use the `BudgetChecker`.

        Returns the impact of the fee on the cost requirements for the candidate order.
        """
        ret = None
        if self.percent != S_DECIMAL_0:
            fee_token = self.percent_token or order_candidate.order_collateral.token
            if order_candidate.order_collateral is None or fee_token != order_candidate.order_collateral.token:
                token, size = order_candidate.get_size_token_and_order_size()
                if fee_token == token:
                    exchange_rate = Decimal("1")
                else:
                    exchange_pair = combine_to_hb_trading_pair(token, fee_token)  # buy order token w/ pf token
                    exchange_rate = exchange.get_price(exchange_pair, is_buy=True)
                fee_amount = size * exchange_rate * self.percent
            else:  # self.percent_token == order_candidate.order_collateral.token
                fee_amount = order_candidate.order_collateral.amount * self.percent
            ret = TokenAmount(fee_token, fee_amount)
        return ret

    def get_fee_impact_on_order_returns(
            self, order_candidate: "OrderCandidate", exchange: "ExchangeBase"
    ) -> Optional[Decimal]:
        """
        WARNING: Do not use this method for sizing. Instead, use the `BudgetChecker`.

        Returns the impact of the fee on the expected returns from the candidate order.
        """
        return None


class DeductedFromReturnsTradeFee(AmmTradeFeeBase):

    @classmethod
    def type_descriptor_for_json(cls) -> str:
        return "DeductedFromReturns"

    def get_fee_impact_on_order_cost(
            self, order_candidate: "OrderCandidate", exchange: "ExchangeBase"
    ) -> Optional[TokenAmount]:
        """
        WARNING: Do not use this method for sizing. Instead, use the `BudgetChecker`.

        Returns the impact of the fee on the cost requirements for the candidate order.
        """
        return None

    def get_fee_impact_on_order_returns(
            self, order_candidate: "OrderCandidate", exchange: "ExchangeBase"
    ) -> Optional[Decimal]:
        """
        WARNING: Do not use this method for sizing. Instead, use the `BudgetChecker`.

        Returns the impact of the fee on the expected returns from the candidate order.
        """
        impact = order_candidate.potential_returns.amount * self.percent
        return impact

def build_trade_fee(
    exchange: str,
    is_maker: bool,
    base_currency: str,
    quote_currency: str,
    order_type: OrderType,
    order_side: TradeType,
    amount: Decimal,
    price: Decimal = Decimal("NaN"),
    extra_flat_fees: Optional[List[TokenAmount]] = None,
) -> AmmTradeFeeBase:
    """
    WARNING: Do not use this method for order sizing. Use the `BudgetChecker` instead.

    Uses the exchange's `TradeFeeSchema` to build a `TradeFee`, given the trade parameters.
    """
    trade_fee_schema: TradeFeeSchema = TradeFeeSchemaLoader.configured_schema_for_exchange(exchange_name=exchange)
    fee_percent: Decimal = (
        trade_fee_schema.maker_percent_fee_decimal
        if is_maker
        else trade_fee_schema.taker_percent_fee_decimal
    )
    fixed_fees: List[TokenAmount] = (
        trade_fee_schema.maker_fixed_fees
        if is_maker
        else trade_fee_schema.taker_fixed_fees
    ).copy()
    if extra_flat_fees is not None and len(extra_flat_fees) > 0:
        fixed_fees = fixed_fees + extra_flat_fees
    trade_fee: AmmTradeFeeBase = AmmTradeFeeBase.new_spot_fee(
        fee_schema=trade_fee_schema,
        trade_type=order_side,
        percent=fee_percent,
        percent_token=trade_fee_schema.percent_fee_token,
        flat_fees=fixed_fees
    )
    return trade_fee


@dataclass
class ArbProposalSide:
    """
    An arbitrage proposal side which contains info needed for order submission.
    """
    market_info: MarketTradingPairTuple
    is_buy: bool
    quote_price: Decimal
    order_price: Decimal
    amount: Decimal
    extra_flat_fees: List[TokenAmount]
    completed_event: asyncio.Event = asyncio.Event()
    failed_event: asyncio.Event = asyncio.Event()

    def __repr__(self):
        side = "buy" if self.is_buy else "sell"
        return f"Connector: {self.market_info.market.display_name}  Side: {side}  Quote Price: {self.quote_price}  " \
               f"Order Price: {self.order_price}  Amount: {self.amount}  Extra Fees: {self.extra_flat_fees}"

    @property
    def is_completed(self) -> bool:
        return self.completed_event.is_set()

    @property
    def is_failed(self) -> bool:
        return self.failed_event.is_set()

    def set_completed(self):
        self.completed_event.set()

    def set_failed(self):
        self.failed_event.set()


class ArbProposal:
    @classmethod
    def logger(cls) -> HummingbotLogger:
        global arbprop_logger
        if arbprop_logger is None:
            arbprop_logger = logging.getLogger(__name__)
        return arbprop_logger

    """
    An arbitrage proposal which contains 2 sides of the proposal - one buy and one sell.
    """
    def __init__(self, first_side: ArbProposalSide, second_side: ArbProposalSide):
        if first_side.is_buy == second_side.is_buy:
            raise Exception("first_side and second_side must be on different side of buy and sell.")
        self.first_side: ArbProposalSide = first_side
        self.second_side: ArbProposalSide = second_side

    @property
    def has_failed_orders(self) -> bool:
        return any([self.first_side.is_failed, self.second_side.is_failed])

    def profit_pct(
            self,
            rate_source: Optional[RateOracle] = None,
            account_for_fee: bool = False,
            use_fixed_conversion_rate: bool = False,
            taker_to_maker_quote_conversion_rate: Decimal = Decimal("1"),
    ) -> Decimal:
        """
        Returns a profit in percentage value (e.g. 0.01 for 1% profitability)
        Assumes the base token is the same in both arbitrage sides
        """
        if not rate_source:
            rate_source = RateOracle.get_instance()

        buy_side: ArbProposalSide = self.first_side if self.first_side.is_buy else self.second_side
        sell_side: ArbProposalSide = self.first_side if not self.first_side.is_buy else self.second_side
        base_conversion_pair: str = f"{sell_side.market_info.base_asset}-{buy_side.market_info.base_asset}"
        quote_conversion_pair: str = f"{sell_side.market_info.quote_asset}-{buy_side.market_info.quote_asset}"

        sell_base_to_buy_base_rate: Decimal = Decimal(1)
        if not use_fixed_conversion_rate:
            sell_quote_to_buy_quote_rate: Decimal = rate_source.get_pair_rate(quote_conversion_pair)
        else:
            sell_quote_to_buy_quote_rate: Decimal = taker_to_maker_quote_conversion_rate
        buy_fee_amount: Decimal = s_decimal_0
        sell_fee_amount: Decimal = s_decimal_0
        result: Decimal = s_decimal_0

        if sell_quote_to_buy_quote_rate and sell_base_to_buy_base_rate:
            if account_for_fee:
                buy_trade_fee: AmmTradeFeeBase = build_trade_fee(
                    exchange=buy_side.market_info.market.name,
                    is_maker=False,
                    base_currency=buy_side.market_info.base_asset,
                    quote_currency=buy_side.market_info.quote_asset,
                    order_type=OrderType.MARKET,
                    order_side=TradeType.BUY,
                    amount=buy_side.amount,
                    price=buy_side.order_price,
                    extra_flat_fees=buy_side.extra_flat_fees
                )
                sell_trade_fee: AmmTradeFeeBase = build_trade_fee(
                    exchange=sell_side.market_info.market.name,
                    is_maker=False,
                    base_currency=sell_side.market_info.base_asset,
                    quote_currency=sell_side.market_info.quote_asset,
                    order_type=OrderType.MARKET,
                    order_side=TradeType.SELL,
                    amount=sell_side.amount,
                    price=sell_side.order_price,
                    extra_flat_fees=sell_side.extra_flat_fees
                )
                buy_fee_amount: Decimal = buy_trade_fee.fee_amount_in_token(
                    trading_pair=buy_side.market_info.trading_pair,
                    price=buy_side.quote_price,
                    order_amount=buy_side.amount,
                    token=buy_side.market_info.quote_asset,
                    rate_source=rate_source,
                    taker_to_maker_quote_conversion_rate=taker_to_maker_quote_conversion_rate
                )
                sell_fee_amount: Decimal = sell_trade_fee.fee_amount_in_token(
                    trading_pair=sell_side.market_info.trading_pair,
                    price=sell_side.quote_price,
                    order_amount=sell_side.amount,
                    token=sell_side.market_info.quote_asset,
                    rate_source=rate_source,
                    taker_to_maker_quote_conversion_rate=taker_to_maker_quote_conversion_rate
                )

            buy_spent_net: Decimal = (buy_side.amount * buy_side.quote_price) + buy_fee_amount
            sell_gained_net: Decimal = (sell_side.amount * sell_side.quote_price) - sell_fee_amount
            sell_gained_net_in_buy_quote_currency: Decimal = (
                sell_gained_net * sell_quote_to_buy_quote_rate / sell_base_to_buy_base_rate
            )

            result: Decimal = (
                ((sell_gained_net_in_buy_quote_currency - buy_spent_net) / buy_spent_net)
                if buy_spent_net != s_decimal_0
                else s_decimal_0
            )
        else:
            self.logger().warning("The arbitrage proposal profitability could not be calculated due to a missing rate"
                                  f" ({base_conversion_pair}={sell_base_to_buy_base_rate},"
                                  f" {quote_conversion_pair}={sell_quote_to_buy_quote_rate})")
        return result

    def __repr__(self):
        return f"First Side - {self.first_side}\nSecond Side - {self.second_side}"

    def copy(self):
        return ArbProposal(
            ArbProposalSide(self.first_side.market_info, self.first_side.is_buy,
                            self.first_side.quote_price, self.first_side.order_price,
                            self.first_side.amount, self.first_side.extra_flat_fees),
            ArbProposalSide(self.second_side.market_info, self.second_side.is_buy,
                            self.second_side.quote_price, self.second_side.order_price,
                            self.second_side.amount, self.second_side.extra_flat_fees)
        )

    async def wait(self):
        return await safe_gather(*[self.first_side.completed_event.wait(), self.second_side.completed_event.wait()])

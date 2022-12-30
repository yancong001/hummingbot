import pandas as pd
import requests
from decimal import Decimal
import logging
import numpy as np

from hummingbot.strategy.script_strategy_base import ScriptStrategyBase
from hummingbot.core.event.events import OrderType
from hummingbot.core.event.events import (
    BuyOrderCompletedEvent,
    BuyOrderCreatedEvent,
    MarketOrderFailureEvent,
    OrderCancelledEvent,
    OrderFilledEvent,
    SellOrderCompletedEvent,
    SellOrderCreatedEvent,
)


# ------------------------------------------------------------------------------------------- #

def abstract_keys(coins_dict):
    # Abstract coin name
    coins = []
    for coin in coins_dict.keys():
        coins.append(coin)
    return coins


def make_pairs(coins, hold_asset):
    # Make coin list
    pairs = []
    for coin in coins:
        pair = coin + "-" + hold_asset
        pairs.append(pair)
    return pairs


def get_klines(pair, interval, limit):
    url = "https://api.binance.us/api/v3/klines"
    params = {"symbol": pair.replace("-", ""),
              "interval": interval, 'limit': limit}
    klines = requests.get(url=url, params=params).json()
    df = pd.DataFrame(klines)
    df = df.drop(columns={6, 7, 8, 9, 10, 11})
    df = df.rename(columns={0: 'timestamps', 1: 'open', 2: 'high', 3: 'low', 4: 'close', 5: 'volume', })
    df = df.fillna(0)
    df[["open", "high", "low", "close", "volume"]] = df[["open", "high", "low", "close", "volume"]].astype(float)
    df['timestamps'] = pd.to_datetime(df['timestamps'], unit='ms')
    return df


def tr(data):
    data['previous_close'] = data['close'].shift(1)
    data['high-low'] = abs(data['high'] - data['low'])
    data['high-pc'] = abs(data['high'] - data['previous_close'])
    data['low-pc'] = abs(data['low'] - data['previous_close'])

    _tr = data[['high-low', 'high-pc', 'low-pc']].max(axis=1)

    return _tr


def atr(data, period):
    data['tr'] = tr(data)
    _atr = data['tr'].rolling(period).mean()

    return _atr


def supertrend(data, period=13, atr_multiplier=3.):
    # Compute ATR
    data['atr'] = data['high'] - data['low']
    data['atr'] = data['atr'].rolling(period).mean()
    data['atr'] = data['atr'] * atr_multiplier

    # Compute upper and lower bands
    data['upperband'] = data['high'] - data['low']
    data['upperband'] = data['upperband'].rolling(period).mean()
    data['upperband'] = data['upperband'] * atr_multiplier
    data['upperband'] = data['high'] - data['upperband']

    data['lowerband'] = data['high'] - data['low']
    data['lowerband'] = data['lowerband'].rolling(period).mean()
    data['lowerband'] = data['lowerband'] * atr_multiplier
    data['lowerband'] = data['low'] + data['lowerband']

    # Define SuperTrend based on upper and lower bands
    data['SuperTrend'] = data['upperband']
    data['SuperTrend'] = data['SuperTrend'].where(data['close'] > data['SuperTrend'], data['lowerband'])

    # Identify uptrend and downtrend
    data['uptrend'] = data['SuperTrend'] > data['close']
    data['downtrend'] = data['SuperTrend'] < data['close']
    print(data['uptrend'],type(data['uptrend']))
    print(data['downtrend'],type(data['downtrend']))

    return data


# ------------------------------------------------------------------------------------------- #


class AutoRebalance(ScriptStrategyBase):
    # Set connector name
    connector_name = "binance_paper_trade"

    # Initialize timestamp and order time
    last_ordered_ts = 0.
    order_interval = 10.

    # Set hold asset configuration
    hold_asset_config = {"BUSD": Decimal('30.00')}

    # Set a list of coins configurations
    coin_config = {
        "BTC": Decimal('20.00'),
        "ETH": Decimal('15.00'),
        "BNB": Decimal('15.00'),
        "RNDR": Decimal('10.00'),
        "DOGE": Decimal('10.00')
    }

    # Set rebalance threshold
    threshold = Decimal('1.00')

    # Abstract coin name and Make coin list
    hold_asset = abstract_keys(hold_asset_config)[0]
    coins = abstract_keys(coin_config)
    pairs = make_pairs(coins, hold_asset)

    # Put connector and pairs into markets
    markets = {connector_name: pairs}

    # Set klines configuration
    last_data_ts = 0.
    data_interval = 900.
    market_pair = "BTC-BUSD"
    interval = "15m"
    limit = 34

    # Set long and short atr configuration
    atr_period = 13
    l_atr_period = 34
    atr = 0.
    l_atr = 0.
    is_volatile = "True"

    # Set SuperTrend configuration
    trend_atr_period = 13
    atr_mult = 3.
    upperband = 0.
    lowerband = 0.
    supertrend = 0.
    preclose = 0.
    uptrend = ""
    downtrend = ""

    @property
    def connector(self):
        """
        The only connector in this strategy, define it here for easy access
        """
        return self.connectors[self.connector_name]

    def on_tick(self):
        exchange = self.connector

        if self.last_data_ts < (self.current_timestamp - self.data_interval):
            # Get Kline data
            btc_df = get_klines(self.market_pair, self.interval, self.limit)

            # ATR indicator
            # Calculate long and short ATR
            btc_df['atr'] = atr(btc_df, 13)
            self.atr = btc_df.iloc[-1]['atr']
            btc_df['l_atr'] = atr(btc_df, 34)
            self.l_atr = btc_df.iloc[-1]['l_atr']
            btc_df['is_volatile'] = btc_df['atr'] > btc_df['l_atr']
            self.is_volatile = btc_df.iloc[-1]['is_volatile']

            # SuperTrend indicator
            btc_df = supertrend(btc_df, self.trend_atr_period, self.atr_mult)
            self.upperband = btc_df.iloc[-1]['upperband']
            self.lowerband = btc_df.iloc[-1]['lowerband']
            self.uptrend = btc_df.iloc[-1]['uptrend']
            self.downtrend = btc_df.iloc[-1]['downtrend']
            self.preclose = btc_df.iloc[-1]['close']
            self.supertrend = btc_df.iloc[-1]['SuperTrend']

            # Update data timestamp
            self.last_data_ts = self.current_timestamp

        # Set threshold according to volatility
        if self.is_volatile == "False":
            self.threshold = Decimal('1.00')
        else:
            self.threshold = Decimal('2.00')

        # Set coins ratio according to the trend
        if self.uptrend == True and self.downtrend == False:
            self.hold_asset_config.update({"BUSD": Decimal('10.00')})
            self.coin_config.update({"BTC": Decimal('30.00'), "ETH": Decimal('20.00'),
                                     "BNB": Decimal('20.00'), "RNDR": Decimal('10.00'), "DOGE": Decimal('10.00')})
        elif self.uptrend == False and self.downtrend == True:
            self.hold_asset_config.update({"BUSD": Decimal('60.00')})
            self.coin_config.update({"BTC": Decimal('10.00'), "ETH": Decimal('10.00'),
                                     "BNB": Decimal('10.00'), "RNDR": Decimal('5.00'), "DOGE": Decimal('5.00')})
        else:
            self.hold_asset_config.update({"BUSD": Decimal('30.00')})
            self.coin_config.update({"BTC": Decimal('20.00'), "ETH": Decimal('15.00'),
                                     "BNB": Decimal('15.00'), "RNDR": Decimal('10.00'), "DOGE": Decimal('10.00')})

        # Check if it is time to rebalance
        if self.last_ordered_ts < (self.current_timestamp - self.order_interval):

            # Calculate all coins weight
            current_weight = self.get_current_weight(self.coins)
            # Cancel all orders
            self.cancel_all_orders()

            # Run over all coins
            for coin in self.coins:
                pair = coin + "-" + self.hold_asset
                if current_weight[coin] >= \
                        (Decimal((self.coin_config[coin] / 100)) * (Decimal('1.00') + (self.threshold / 100))):
                    self.sell(self.connector_name, pair, self.order_amount(coin, self.coins), OrderType.LIMIT,
                              Decimal(exchange.get_price(pair, True) * Decimal('1.0001')).quantize(Decimal('1.00')))
                elif current_weight[coin] <= \
                        ((Decimal(self.coin_config[coin] / 100)) * (Decimal('1.00') - (self.threshold / 100))):
                    self.buy(self.connector_name, pair, self.order_amount(coin, self.coins), OrderType.LIMIT,
                             Decimal(exchange.get_price(pair, False) * Decimal('0.9999')).quantize(Decimal('1.00')))
            # Set timestamp
            self.last_ordered_ts = self.current_timestamp

    def get_current_value(self, coins):
        """
        Get current value of each coin and make it a dictionary
        """
        exchange = self.connector
        current_value = {}
        for coin in coins:
            pair = coin + "-" + self.hold_asset
            current_value[coin] = Decimal((exchange.get_balance(coin) *
                                           exchange.get_mid_price(pair))).quantize(Decimal('1.0000'))
        return current_value

    def get_total_value(self, coins):
        """
        Get Sum of all value
        """
        exchange = self.connector
        total_value = exchange.get_balance(self.hold_asset)
        current_value = self.get_current_value(coins)
        for coin in current_value:
            total_value = total_value + current_value[coin]
        return total_value

    def get_current_weight(self, coins):
        """
        Get current weight of each coin
        """
        total_value = self.get_total_value(coins)
        current_value_dict = self.get_current_value(coins)
        current_weight = {}
        for coin in coins:
            current_value = current_value_dict[coin]
            current_weight[coin] = Decimal((current_value / total_value)).quantize(Decimal('1.0000'))
        return current_weight

    def order_amount(self, coin, coins):
        """
        Calculate order amount
        """
        exchange = self.connector
        pair = coin + "-" + self.hold_asset
        order_amount = Decimal((self.get_current_value(coins)[coin] -
                                (self.get_total_value(coins) * (self.coin_config[coin] / 100))) /
                               exchange.get_mid_price(pair)).quantize(Decimal('1.000'))
        order_amount = abs(order_amount)
        return order_amount

    def cancel_all_orders(self):
        """
        Cancel all orders from the bot
        """
        for order in self.get_active_orders(connector_name=self.connector_name):
            self.cancel(self.connector_name, order.trading_pair, order.client_order_id)

    # ------------------------------------------------------------------------------------------- #

    def did_create_buy_order(self, event: BuyOrderCreatedEvent):
        """
        Method called when the connector notifies a buy order has been created
        """
        self.logger().info(logging.INFO, f"The buy order {event.order_id} has been created")

    def did_create_sell_order(self, event: SellOrderCreatedEvent):
        """
        Method called when the connector notifies a sell order has been created
        """
        self.logger().info(logging.INFO, f"The sell order {event.order_id} has been created")

    def did_fill_order(self, event: OrderFilledEvent):
        """
        Method called when the connector notifies that an order has been partially or totally filled (a trade happened)
        """
        self.logger().info(logging.INFO, f"The order {event.order_id} has been filled")

    def did_fail_order(self, event: MarketOrderFailureEvent):
        """
        Method called when the connector notifies an order has failed
        """
        self.logger().info(logging.INFO, f"The order {event.order_id} failed")

    def did_cancel_order(self, event: OrderCancelledEvent):
        """
        Method called when the connector notifies an order has been cancelled
        """
        self.logger().info(f"The order {event.order_id} has been cancelled")

    def did_complete_buy_order(self, event: BuyOrderCompletedEvent):
        """
        Method called when the connector notifies a buy order has been completed (fully filled)
        """
        self.logger().info(f"The buy order {event.order_id} has been completed")

    def did_complete_sell_order(self, event: SellOrderCompletedEvent):
        """
        Method called when the connector notifies a sell order has been completed (fully filled)
        """
        self.logger().info(f"The sell order {event.order_id} has been completed")

    def format_status(self) -> str:
        """
        Returns status of the current strategy on user balances and current active orders. This function is called
        when status command is issued. Override this function to create custom status display output.
        """
        if not self.ready_to_trade:
            return "Market connectors are not ready."
        lines = []
        warning_lines = []
        warning_lines.extend(self.network_warning(self.get_market_trading_pair_tuples()))

        balance_df = self.get_balance_df().drop('Exchange', axis=1)

        asset = self.coins + [self.hold_asset]

        current_value = []
        for coin in self.get_current_value(self.coins):
            current_value.append(self.get_current_value(self.coins)[coin])
        current_value.append(Decimal((self.connector.get_balance(self.hold_asset))).quantize(Decimal('1.00')))

        current_weight = []
        current_weight_total = Decimal('0.0000')
        for coin in self.get_current_weight(self.coins):
            current_weight_total = current_weight_total + self.get_current_weight(self.coins)[coin]
            current_weight.append(self.get_current_weight(self.coins)[coin])
        hold_asset_current_weight = Decimal('1.0000') - current_weight_total
        current_weight.append(hold_asset_current_weight)

        target_weight = []
        for coin in self.coin_config.values():
            target_weight.append(coin)
        target_weight.append(self.hold_asset_config[self.hold_asset])

        weight_df = pd.DataFrame({
            "Asset": asset,
            "Current Value": current_value,
            "Current Weight": current_weight,
            "Target Weight": target_weight
        })
        weight_df["Current Weight"] = weight_df["Current Weight"].apply(lambda x: '%.2f%%' % (x * 100))
        weight_df["Target Weight"] = weight_df["Target Weight"].apply(lambda x: '%.2f%%' % x)
        account_data = pd.merge(left=balance_df, right=weight_df, how='left', on='Asset')

        lines.extend(["", f"  Exchange: {self.connector_name}"])
        lines.extend(["", "  Balances:\n"] +
                     ["  " + line for line in account_data.to_string(index=False).split("\n")])
        lines.extend(["", f"  Current threshold: {self.threshold}\n"])
        lines.extend(["", "  Active Orders:\n"])
        try:
            active_order = self.active_orders_df().drop('Exchange', axis=1)
            lines.extend(["  " + line for line in active_order.to_string(index=False).split("\n")])
        except ValueError:
            lines.extend(["", "  No active maker orders."])

        lines.extend(["", "  Trend Info:\n"])
        lines.extend([f"  | Short period ATR: {np.round(self.atr, 4)} |" +
                      f"  Long period ATR: {np.round(self.l_atr, 4)} |" + f"  Is volatile: {self.is_volatile} |\n"] +
                     [f"  | SuperTrend upperband: {np.round(self.upperband, 4)} |" +
                      f"  SuperTrend lowerband: {np.round(self.lowerband, 4)} |"] +
                     [f"  | SuperTrend: {np.round(self.supertrend, 4)}             |" +
                      f"  SuperTrend preclose: {np.round(self.preclose, 4)}    |"] +
                     [f"  | SuperTrend uptrend: {self.uptrend}        |" +
                      f"  SuperTrend downtrend: {self.downtrend}       |"])

        warning_lines.extend(self.balance_warning(self.get_market_trading_pair_tuples()))
        if len(warning_lines) > 0:
            lines.extend(["", "*** WARNINGS ***"] + warning_lines)
        return "\n".join(lines)

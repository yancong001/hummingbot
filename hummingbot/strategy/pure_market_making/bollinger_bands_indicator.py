# from ..__utils__.trailing_indicators.base_trend_indicator import BaseTrendIndicator
from hummingbot.strategy.pure_market_making.base_trend_indicator import BaseTrendIndicator

import numpy as np
from decimal import Decimal

# import pandas as pd

class BollingerBandsIndicator(BaseTrendIndicator):
    def __init__(self, sampling_length: int = 30, processing_length: int = 15, alpha: float=2.0, offset = 0):
        super().__init__(sampling_length, processing_length)
        self.alpha = alpha
        self.offset = offset


    def add_sample(self,value):
        if self.is_sampling_buffer_full:
            self._sampling_buffer.pop(0)
        if self.is_processing_buffer_full:
            self._processing_buffer.pop(0)

        orderbook_timestamp = value.timestamp
        if len(self._sampling_buffer) > 0 and int(orderbook_timestamp) < int(self._sampling_buffer[-1].timestamp):
            return
        elif len(self._sampling_buffer) > 0 and int(orderbook_timestamp) == int(self._sampling_buffer[-1].timestamp):
            self._sampling_buffer[-1] = value
        else:
            self._sampling_buffer.append(value)
        indicator_value = self._indicator_calculation()
        if indicator_value:
            self._processing_buffer.append(indicator_value)
    def _indicator_calculation(self):
        data = self._sampling_buffer
        price_data = [i.price for i in self._sampling_buffer]
        if len(price_data) >= 2:
            std = np.std(price_data)
            mid_band = np.mean(price_data)
            upper_band = Decimal(str(mid_band)) + Decimal(str(self.alpha)) * Decimal(str(std)) + Decimal(str(self.offset))
            lower_band = Decimal(str(mid_band)) - Decimal(str(self.alpha)) * Decimal(str(std)) + Decimal(str(self.offset))
            return upper_band, lower_band

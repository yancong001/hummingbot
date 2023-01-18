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
    def _indicator_calculation(self):
        data = self._sampling_buffer
        if len(data) >= 2:
            std = np.std(data)
            mid_band = np.mean(data)
            upper_band = Decimal(str(mid_band)) + Decimal(str(self.alpha)) * Decimal(str(std)) + Decimal(str(self.offset))
            lower_band = Decimal(str(mid_band)) - Decimal(str(self.alpha)) * Decimal(str(std)) + Decimal(str(self.offset))
            return upper_band, lower_band

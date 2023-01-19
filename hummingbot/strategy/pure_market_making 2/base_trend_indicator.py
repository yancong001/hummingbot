from abc import ABC, abstractmethod
import numpy as np
from decimal import Decimal
import logging
# from ..ring_buffer import RingBuffer

pmm_logger = None


class BaseTrendIndicator(ABC):
    @classmethod
    def logger(cls):
        global pmm_logger
        if pmm_logger is None:
            pmm_logger = logging.getLogger(__name__)
        return pmm_logger

    def __init__(self, sampling_length: int = 30, processing_length: int = 15):
        self._sampling_length = sampling_length
        self._sampling_buffer = []
        self._processing_length = processing_length
        self._processing_buffer = []

    def add_sample(self, value: Decimal):
        if self.is_sampling_buffer_full:
            self._sampling_buffer.pop(0)
        if self.is_processing_buffer_full:
            self._processing_buffer.pop(0)
        self._sampling_buffer.append(value)
        indicator_value = self._indicator_calculation()

        self._processing_buffer.append(indicator_value)

    @abstractmethod
    def _indicator_calculation(self) -> float:
        raise NotImplementedError


    @property
    def current_value(self) -> float:
        return self._processing_calculation()

    @property
    def is_sampling_buffer_full(self) -> bool:
        return len(self._sampling_buffer) >= self._sampling_length

    @property
    def sampling_length_left(self) -> int:
        return self._sampling_length - len(self._sampling_buffer)

    @property
    def is_processing_buffer_full(self) -> bool:
        return len(self._processing_buffer) >= self._processing_length

    def _processing_calculation(self) -> float:
        # Only the last calculated volatlity, not an average of multiple past volatilities
        return self._processing_buffer[-1]
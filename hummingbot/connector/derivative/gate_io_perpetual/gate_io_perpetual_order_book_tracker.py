import asyncio

from typing import Optional, List
from hummingbot.core.data_type.order_book_tracker import OrderBookTracker
from hummingbot.core.utils.async_utils import safe_ensure_future
from hummingbot.logger import HummingbotLogger


class GateIoPerpetualOrderBookTracker(OrderBookTracker):
    _bpobt_logger: Optional[HummingbotLogger] = None

    def __init__(self,
                 data_source,
                 trading_pairs: Optional[List[str]] = None,
                 domain: str = "",
                 connector=None
                 ):
        super().__init__(data_source=data_source,
                         trading_pairs=trading_pairs, domain=domain)
        self._connector = connector

    async def _init_order_books(self):
        """
        Initialize order books
        """
        try:
            await self._connector._update_trading_rules()
        except NotImplementedError:
            raise
        except asyncio.CancelledError:
            raise
        except Exception:
            self.logger().network(
                "Unexpected error while fetching trading rules.", exc_info=True,
                app_warning_msg=f"Could not fetch new trading rules from {self.name_cap}"
                                " Check network connection.")
            await asyncio.sleep(0.5)
        for index, trading_pair in enumerate(self._trading_pairs):
            self._order_books[trading_pair] = await self._initial_order_book_for_trading_pair(trading_pair)
            self._tracking_message_queues[trading_pair] = asyncio.Queue()
            self._tracking_tasks[trading_pair] = safe_ensure_future(self._track_single_book(trading_pair))
            self.logger().info(f"Initialized order book for {trading_pair}. "
                               f"{index + 1}/{len(self._trading_pairs)} completed.")
            await asyncio.sleep(1)
        self._order_books_initialized.set()

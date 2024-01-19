from decimal import Decimal
from hummingbot.core.data_type.common import PriceType

from hummingbot.data_feed.custom_api_data_feed import CustomAPIDataFeed, NetworkStatus

class WtCustomAPIDataFeed(CustomAPIDataFeed):
    def __init__(self, api_url, update_interval: float = 5.0):
        super().__init__(api_url, update_interval)

    async def fetch_price(self):
        client = self._http_client()
        async with client.request("GET", self._api_url) as resp:
            resp_text = await resp.json()
            resp_json = resp_text.get("pairs",{})[0].get("priceUsd")
            if resp.status != 200:
                raise Exception(f"Custom API Feed {self.name} server error: {resp_json}")
            self._price = Decimal(str(resp_json))
        self._ready_event.set()

class WtAPIAssetPriceDelegate():
    def __init__(self, market, api_url: str, update_interval: float = 5.0):
        super().__init__()
        self._market = market
        self._custom_api_feed = WtCustomAPIDataFeed(api_url=api_url, update_interval=update_interval)
        self._custom_api_feed.start()

    def get_price_by_type(self, _: PriceType) -> Decimal:
        return self._custom_api_feed.get_price()

    @property
    def ready(self) -> bool:
        return self._custom_api_feed.network_status == NetworkStatus.CONNECTED

    @property
    def market(self):
        return self._market

    @property
    def custom_api_feed(self) -> CustomAPIDataFeed:
        return self._custom_api_feed

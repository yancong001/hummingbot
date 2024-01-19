from decimal import Decimal

from hummingbot.strategy.api_asset_price_delegate import APIAssetPriceDelegate
from hummingbot.data_feed.custom_api_data_feed import CustomAPIDataFeed

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

class WtAPIAssetPriceDelegate(APIAssetPriceDelegate):
    def __init__(self, market, api_url: str, update_interval: float = 5.0):
        super().__init__(market, api_url, update_interval)
        self._custom_api_feed = WtCustomAPIDataFeed(api_url=api_url, update_interval=update_interval)

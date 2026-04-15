"""Google Merchant Center connector — Phase 2 skeleton."""

from catalog_bridge.connectors.base import CatalogConnector


class GoogleMerchantConnector(CatalogConnector):
    """Phase 2: Google Merchant Center connector."""

    def transform(self, website_item) -> dict:
        raise NotImplementedError("Google Merchant connector not yet implemented")

    def push(self, product_data: dict) -> dict:
        raise NotImplementedError("Google Merchant connector not yet implemented")

    def delete(self, retailer_id: str) -> dict:
        raise NotImplementedError("Google Merchant connector not yet implemented")

    def list_products(self) -> list[dict]:
        raise NotImplementedError("Google Merchant connector not yet implemented")

    def get_product(self, retailer_id: str) -> dict:
        raise NotImplementedError("Google Merchant connector not yet implemented")

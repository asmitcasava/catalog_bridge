"""Base connector interface for catalog platforms."""

import time
import frappe


class CatalogConnector:
    """Base class for platform connectors."""

    def __init__(self, platform_doc):
        self.platform = platform_doc

    def transform(self, website_item) -> dict:
        """Transform Website Item fields to platform-specific format."""
        raise NotImplementedError

    def push(self, product_data: dict) -> dict:
        """Upsert a single product to the platform.

        Creates if it doesn't exist, updates if it does.
        Returns API response dict.
        """
        raise NotImplementedError

    def delete(self, retailer_id: str) -> dict:
        """Delete a product from the platform."""
        raise NotImplementedError

    def list_products(self) -> list[dict]:
        """Fetch all products currently on the platform."""
        raise NotImplementedError

    def get_product(self, retailer_id: str) -> dict:
        """Fetch a single product from the platform by retailer_id."""
        raise NotImplementedError

    def bulk_push(self, products: list[dict]) -> dict:
        """Push multiple products with rate limiting.

        Default: loop over push() with 100ms delay.
        Platform connectors should override to use batch APIs.
        """
        results = {"success": 0, "failed": 0, "errors": []}
        for product in products:
            try:
                self.push(product)
                results["success"] += 1
                time.sleep(0.1)
            except Exception as e:
                results["failed"] += 1
                results["errors"].append(str(e))
        return results


def get_connector(platform_doc) -> CatalogConnector:
    """Factory: return the right connector for a platform."""
    if platform_doc.platform_type == "Meta Catalog":
        from catalog_bridge.connectors.meta_catalog import MetaCatalogConnector
        return MetaCatalogConnector(platform_doc)
    elif platform_doc.platform_type == "Google Merchant Center":
        from catalog_bridge.connectors.google_merchant import GoogleMerchantConnector
        return GoogleMerchantConnector(platform_doc)
    frappe.throw(f"Unknown platform type: {platform_doc.platform_type}")

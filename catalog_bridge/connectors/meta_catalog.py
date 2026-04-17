"""Meta WhatsApp Catalog connector."""

import json
import time

import frappe
from frappe.integrations.utils import make_request, make_post_request

from catalog_bridge.connectors.base import CatalogConnector


class MetaCatalogConnector(CatalogConnector):
    """Push products to Meta's WhatsApp Catalog via the Graph API."""

    def __init__(self, platform_doc):
        super().__init__(platform_doc)
        self._credentials = None

    def _get_credentials(self):
        if self._credentials:
            return self._credentials

        account = frappe.get_doc("WhatsApp Account", self.platform.whatsapp_account)
        self._credentials = {
            "token": account.get_password("token"),
            "url": account.url,
            "version": account.version,
            "business_id": account.business_id,
        }
        return self._credentials

    def _headers(self):
        creds = self._get_credentials()
        return {
            "authorization": f"Bearer {creds['token']}",
            "content-type": "application/json",
        }

    def _api_base(self):
        creds = self._get_credentials()
        return f"{creds['url']}/{creds['version']}"

    def push(self, product_data: dict) -> dict:
        """Upsert a product to Meta Catalog."""
        catalog_id = self.platform.catalog_id
        base = self._api_base()
        id_field = self.get_id_field()

        payload = [{"method": "UPDATE", "retailer_id": product_data[id_field], "data": product_data}]

        response = make_post_request(
            f"{base}/{catalog_id}/batch",
            headers=self._headers(),
            data=json.dumps({"requests": payload}),
        )
        return response

    def delete(self, retailer_id: str) -> dict:
        """Delete a product from Meta Catalog."""
        catalog_id = self.platform.catalog_id
        base = self._api_base()

        payload = [{"method": "DELETE", "retailer_id": retailer_id}]

        response = make_post_request(
            f"{base}/{catalog_id}/batch",
            headers=self._headers(),
            data=json.dumps({"requests": payload}),
        )
        return response

    def list_products(self) -> list[dict]:
        """Fetch all products from Meta Catalog with pagination."""
        catalog_id = self.platform.catalog_id
        base = self._api_base()
        headers = self._headers()

        fields = "id,retailer_id,name,description,price,currency,availability,image_url,url,brand,category"
        endpoint = f"{base}/{catalog_id}/products?fields={fields}&limit=100"

        products = []
        while endpoint:
            response = make_request("GET", endpoint, headers=headers)
            products.extend(response.get("data", []))
            paging = response.get("paging", {})
            endpoint = paging.get("next")

        return products

    def get_product(self, retailer_id: str) -> dict:
        """Fetch a single product by retailer_id."""
        catalog_id = self.platform.catalog_id
        base = self._api_base()
        headers = self._headers()

        fields = "id,retailer_id,name,description,price,currency,availability,image_url,url,brand,category"
        response = make_request(
            "GET",
            f"{base}/{catalog_id}/products?fields={fields}&filter={{\"retailer_id\":\"{retailer_id}\"}}",
            headers=headers,
        )
        data = response.get("data", [])
        return data[0] if data else {}

    def bulk_push(self, products: list[dict]) -> dict:
        """Push products using Meta's Batch API (50 items per batch)."""
        catalog_id = self.platform.catalog_id
        base = self._api_base()
        headers = self._headers()
        id_field = self.get_id_field()

        results = {"success": 0, "failed": 0, "errors": []}
        batch_size = 50

        for i in range(0, len(products), batch_size):
            batch = products[i:i + batch_size]
            requests = []
            for product in batch:
                requests.append({
                    "method": "UPDATE",
                    "retailer_id": product[id_field],
                    "data": product,
                })

            try:
                make_post_request(
                    f"{base}/{catalog_id}/batch",
                    headers=headers,
                    data=json.dumps({"requests": requests}),
                )
                results["success"] += len(batch)
            except Exception as e:
                results["failed"] += len(batch)
                results["errors"].append(str(e))

            time.sleep(0.5)

        return results

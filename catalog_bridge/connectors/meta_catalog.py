"""Meta WhatsApp Catalog connector."""

import json
import time

import frappe
from frappe.integrations.utils import make_request, make_post_request
from frappe.utils import strip_html

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

    def transform(self, website_item) -> dict:
        """Transform Website Item to Meta Catalog product format."""
        wi = website_item
        if isinstance(wi, str):
            wi = frappe.get_doc("Website Item", wi)

        data = {
            "retailer_id": wi.item_code,
            "name": wi.web_item_name or wi.item_name,
            "description": strip_html(wi.description or wi.web_long_description or ""),
            "url": self._build_product_url(wi),
            "image_url": self._build_image_url(wi),
            "brand": wi.brand or "",
            "category": wi.item_group or "",
        }

        if wi.short_description:
            data["short_description"] = wi.short_description

        # Price from configured price list
        price_data = self._get_price(wi.item_code)
        if price_data:
            data["price"] = price_data["price"]
            data["currency"] = price_data["currency"]

        # Stock availability
        availability = self._get_availability(wi)
        if availability is not None:
            data["availability"] = availability

        # Apply custom field mapping overrides
        data = self._apply_field_overrides(data, wi)

        return data

    def push(self, product_data: dict) -> dict:
        """Upsert a product to Meta Catalog."""
        catalog_id = self.platform.catalog_id
        base = self._api_base()

        payload = [{"method": "UPDATE", "retailer_id": product_data["retailer_id"], "data": product_data}]

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

        results = {"success": 0, "failed": 0, "errors": []}
        batch_size = 50

        for i in range(0, len(products), batch_size):
            batch = products[i:i + batch_size]
            requests = []
            for product in batch:
                requests.append({
                    "method": "UPDATE",
                    "retailer_id": product["retailer_id"],
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

            # Rate limit: 200 calls/hour, be conservative
            time.sleep(0.5)

        return results

    def _get_price(self, item_code):
        """Get current price from the configured price list."""
        price_list = self.platform.price_list
        price_row = frappe.db.get_value(
            "Item Price",
            {
                "item_code": item_code,
                "price_list": price_list,
                "selling": 1,
            },
            ["price_list_rate", "currency"],
            as_dict=True,
            order_by="valid_from desc",
        )
        if not price_row or not price_row.price_list_rate:
            return None

        return {
            "price": int(float(price_row.price_list_rate) * 100),
            "currency": price_row.currency,
        }

    def _get_availability(self, website_item):
        """Get stock availability from Bin."""
        if not website_item.website_warehouse:
            return None

        qty = frappe.db.get_value(
            "Bin",
            {"item_code": website_item.item_code, "warehouse": website_item.website_warehouse},
            "actual_qty",
        )
        if qty is None:
            return "out of stock"
        return "in stock" if float(qty) > 0 else "out of stock"

    def _build_product_url(self, wi):
        """Build product URL from Jinja template."""
        template = self.platform.product_url_template or "{{ frontend_url }}/{{ route }}"
        frontend_url = self.platform.frontend_url or frappe.utils.get_url()
        frontend_url = frontend_url.rstrip("/")

        try:
            return frappe.render_template(template, {
                "frontend_url": frontend_url,
                "route": wi.route or "",
                "item_code": wi.item_code or "",
                "item_name": wi.item_name or "",
                "name": wi.name or "",
                "web_item_name": wi.web_item_name or "",
            })
        except Exception:
            return f"{frontend_url}/{wi.route or ''}"

    def _build_image_url(self, wi):
        """Build image URL. Absolute URLs pass through unchanged."""
        image = wi.website_image or ""
        if not image:
            return ""
        if image.startswith("http"):
            return image

        template = self.platform.image_url_template or "{{ frontend_url }}{{ website_image }}"
        frontend_url = self.platform.frontend_url or frappe.utils.get_url()
        frontend_url = frontend_url.rstrip("/")

        try:
            return frappe.render_template(template, {
                "frontend_url": frontend_url,
                "website_image": image,
                "item_code": wi.item_code or "",
            })
        except Exception:
            return f"{frontend_url}{image}"

    def _apply_field_overrides(self, data, wi):
        """Apply custom field mapping overrides from Catalog Platform child table."""
        for mapping in self.platform.field_mapping or []:
            source_val = wi.get(mapping.source_field, "")
            if source_val is None:
                source_val = ""

            if mapping.transform == "Strip HTML":
                source_val = strip_html(str(source_val))
            elif mapping.transform == "Price to Cents":
                try:
                    source_val = int(float(source_val) * 100)
                except (ValueError, TypeError):
                    continue
            elif mapping.transform == "Boolean to Availability":
                source_val = "in stock" if source_val else "out of stock"

            data[mapping.target_field] = source_val

        return data

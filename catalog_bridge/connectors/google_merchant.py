"""Google Merchant Center connector using the new Merchant API v1."""

import time

import frappe
from frappe.utils import strip_html

from catalog_bridge.connectors.base import CatalogConnector


class GoogleMerchantConnector(CatalogConnector):
    """Push products to Google Merchant Center via the Merchant Products API v1."""

    def __init__(self, platform_doc):
        super().__init__(platform_doc)
        self._client = None
        self._products_client = None
        self._credentials = None

    def _get_credentials(self):
        if self._credentials:
            return self._credentials

        from google.oauth2 import service_account

        json_file = self.platform.google_service_account_json
        if not json_file:
            frappe.throw("Service Account JSON is not configured on the Catalog Platform.")

        # Read the attached JSON file
        file_doc = frappe.get_doc("File", {"file_url": json_file})
        file_path = file_doc.get_full_path()

        self._credentials = service_account.Credentials.from_service_account_file(file_path)
        return self._credentials

    def _get_product_inputs_client(self):
        if self._client:
            return self._client

        from google.shopping.merchant_products_v1 import ProductInputsServiceClient

        self._client = ProductInputsServiceClient(credentials=self._get_credentials())
        return self._client

    def _get_products_client(self):
        if self._products_client:
            return self._products_client

        from google.shopping.merchant_products_v1 import ProductsServiceClient

        self._products_client = ProductsServiceClient(credentials=self._get_credentials())
        return self._products_client

    @property
    def _merchant_id(self):
        return self.platform.google_merchant_id

    @property
    def _parent(self):
        return f"accounts/{self._merchant_id}"

    @property
    def _content_language(self):
        return self.platform.google_content_language or "en"

    @property
    def _feed_label(self):
        return self.platform.google_feed_label or "online"

    def _get_data_source(self):
        """Get or auto-detect the API data source for this merchant account."""
        if self.platform.google_data_source:
            return self.platform.google_data_source

        # Auto-detect: find the first API-type data source
        from google.shopping.merchant_datasources_v1 import DataSourcesServiceClient

        ds_client = DataSourcesServiceClient(credentials=self._get_credentials())
        try:
            data_sources = ds_client.list_data_sources(parent=self._parent)
            for ds in data_sources:
                # API data sources have primary_product_data_source with channel
                if hasattr(ds, 'primary_product_data_source') and ds.primary_product_data_source:
                    data_source_name = ds.name
                    # Cache it on the platform doc
                    frappe.db.set_value(
                        "Catalog Platform", self.platform.name,
                        "google_data_source", data_source_name,
                    )
                    frappe.db.commit()
                    return data_source_name
        except Exception as e:
            frappe.log_error("Catalog Bridge", f"Failed to auto-detect data source: {e}")

        frappe.throw(
            "Could not find an API data source in your Merchant Center account. "
            "Please create one in Merchant Center > Products > Feeds > Add feed (API), "
            "then set the Data Source field on this platform."
        )

    def transform(self, website_item) -> dict:
        """Transform Website Item to Google Merchant product format."""
        wi = website_item
        if isinstance(wi, str):
            wi = frappe.get_doc("Website Item", wi)

        data = {
            "offer_id": wi.item_code,
            "title": wi.web_item_name or wi.item_name,
            "description": strip_html(wi.description or wi.web_long_description or ""),
            "link": self._build_product_url(wi),
            "image_link": self._build_image_url(wi),
            "brand": wi.brand or "",
            "condition": "new",
            "content_language": self._content_language,
            "feed_label": self._feed_label,
        }

        if wi.item_group:
            data["product_types"] = [wi.item_group]

        # Price from configured price list
        price_data = self._get_price(wi.item_code)
        if price_data:
            data["price_amount_micros"] = price_data["amount_micros"]
            data["price_currency"] = price_data["currency"]

        # Stock availability
        availability = self._get_availability(wi)
        if availability is not None:
            data["availability"] = availability

        # Apply custom field mapping overrides
        data = self._apply_field_overrides(data, wi)

        return data

    def push(self, product_data: dict) -> dict:
        """Upsert a product to Google Merchant Center."""
        from google.shopping.merchant_products_v1 import (
            InsertProductInputRequest,
            ProductInput,
        )
        from google.shopping.merchant_products_v1.types import ProductAttributes
        from google.shopping.type.types import Price

        client = self._get_product_inputs_client()
        data_source = self._get_data_source()

        # Build product attributes
        attrs = {}

        if product_data.get("title"):
            attrs["title"] = product_data["title"]
        if product_data.get("description"):
            attrs["description"] = product_data["description"]
        if product_data.get("link"):
            attrs["link"] = product_data["link"]
        if product_data.get("image_link"):
            attrs["image_link"] = product_data["image_link"]
        if product_data.get("brand"):
            attrs["brand"] = product_data["brand"]
        if product_data.get("condition"):
            attrs["condition"] = product_data["condition"]
        if product_data.get("product_types"):
            attrs["product_types"] = product_data["product_types"]

        # Price
        if product_data.get("price_amount_micros") is not None:
            attrs["price"] = Price(
                amount_micros=product_data["price_amount_micros"],
                currency_code=product_data.get("price_currency", "INR"),
            )

        # Availability
        if product_data.get("availability"):
            attrs["availability"] = product_data["availability"]

        # GTIN / MPN — pass through if present from field overrides
        if product_data.get("gtin"):
            attrs["gtins"] = [product_data["gtin"]]
        if product_data.get("mpn"):
            attrs["mpn"] = product_data["mpn"]

        product_input = ProductInput(
            offer_id=product_data["offer_id"],
            content_language=product_data.get("content_language", self._content_language),
            feed_label=product_data.get("feed_label", self._feed_label),
            channel="ONLINE",
            product_attributes=ProductAttributes(**attrs),
        )

        request = InsertProductInputRequest(
            parent=self._parent,
            product_input=product_input,
            data_source=data_source,
        )

        response = client.insert_product_input(request=request)
        return {"name": response.name, "offer_id": product_data["offer_id"]}

    def delete(self, retailer_id: str) -> dict:
        """Delete a product from Google Merchant Center."""
        from google.shopping.merchant_products_v1 import DeleteProductInputRequest

        client = self._get_product_inputs_client()
        data_source = self._get_data_source()

        # Product input name format: accounts/{merchant}/productInputs/{channel}~{lang}~{feed}~{offer}
        product_name = (
            f"{self._parent}/productInputs/"
            f"online~{self._content_language}~{self._feed_label}~{retailer_id}"
        )

        request = DeleteProductInputRequest(
            name=product_name,
            data_source=data_source,
        )

        try:
            client.delete_product_input(request=request)
            return {"deleted": retailer_id}
        except Exception as e:
            if "NOT_FOUND" in str(e):
                return {"deleted": retailer_id, "note": "already deleted"}
            raise

    def list_products(self) -> list[dict]:
        """Fetch all products from Google Merchant Center."""
        client = self._get_products_client()
        products = []

        try:
            response = client.list_products(parent=self._parent)
            for product in response:
                attrs = product.product_attributes if product.product_attributes else None
                products.append({
                    "retailer_id": product.offer_id or "",
                    "name": product.name,
                    "title": attrs.title if attrs else "",
                    "availability": attrs.availability if attrs else "",
                })
        except Exception as e:
            frappe.log_error("Catalog Bridge", f"Google list_products failed: {e}")

        return products

    def get_product(self, retailer_id: str) -> dict:
        """Fetch a single product from Google Merchant Center."""
        from google.shopping.merchant_products_v1 import GetProductRequest

        client = self._get_products_client()

        product_name = (
            f"{self._parent}/products/"
            f"online~{self._content_language}~{self._feed_label}~{retailer_id}"
        )

        try:
            request = GetProductRequest(name=product_name)
            product = client.get_product(request=request)
            attrs = product.product_attributes if product.product_attributes else None
            return {
                "retailer_id": product.offer_id or retailer_id,
                "name": product.name,
                "title": attrs.title if attrs else "",
                "availability": attrs.availability if attrs else "",
            }
        except Exception as e:
            if "NOT_FOUND" in str(e):
                return {}
            raise

    def bulk_push(self, products: list[dict]) -> dict:
        """Push products one at a time with rate limiting.

        Google Merchant API counts each insert as a separate API call
        against quota, even in batch. We do sequential inserts with a
        small delay to stay within rate limits.
        """
        results = {"success": 0, "failed": 0, "errors": []}

        for product in products:
            try:
                self.push(product)
                results["success"] += 1
                time.sleep(0.2)
            except Exception as e:
                results["failed"] += 1
                results["errors"].append(f"{product.get('offer_id', '?')}: {e}")

        return results

    def _get_price(self, item_code):
        """Get current price from the configured price list. Returns micros."""
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

        # Google uses micros: 1 INR = 1,000,000 micros
        return {
            "amount_micros": int(float(price_row.price_list_rate) * 1_000_000),
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
            return "out_of_stock"
        return "in_stock" if float(qty) > 0 else "out_of_stock"

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
                    source_val = int(float(source_val) * 1_000_000)
                except (ValueError, TypeError):
                    continue
            elif mapping.transform == "Boolean to Availability":
                source_val = "in_stock" if source_val else "out_of_stock"

            data[mapping.target_field] = source_val

        return data

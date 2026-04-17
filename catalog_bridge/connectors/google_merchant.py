"""Google Merchant Center connector using the new Merchant API v1."""

import time

import frappe

from catalog_bridge.connectors.base import CatalogConnector


# Type registry: maps product_data keys to complex protobuf builders.
# Keys not in this registry pass through as simple ProductAttributes kwargs.
COMPLEX_FIELD_BUILDERS = {}


def _build_price(product_data):
    """Build a Google Price proto from price_amount_micros + price_currency."""
    from google.shopping.type.types import Price

    amount = product_data.pop("price_amount_micros", None)
    currency = product_data.pop("price_currency", "INR")
    if amount is None:
        return None
    return Price(amount_micros=int(amount), currency_code=currency)


def _build_shipping_weight(product_data):
    """Build a ShippingWeight proto from shipping_weight_value + shipping_weight_unit."""
    from google.shopping.merchant_products_v1.types import ShippingWeight

    value = product_data.pop("shipping_weight_value", None)
    unit = product_data.pop("shipping_weight_unit", "kg")
    if value is None:
        return None
    return ShippingWeight(value=float(value), unit=str(unit))


COMPLEX_FIELD_BUILDERS["price"] = {
    "keys": ["price_amount_micros", "price_currency"],
    "attr": "price",
    "builder": _build_price,
}
COMPLEX_FIELD_BUILDERS["shipping_weight"] = {
    "keys": ["shipping_weight_value", "shipping_weight_unit"],
    "attr": "shipping_weight",
    "builder": _build_shipping_weight,
}


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
            ds = self.platform.google_data_source
            if not ds.startswith("accounts/"):
                ds = f"{self._parent}/dataSources/{ds}"
            return ds

        from google.shopping.merchant_datasources_v1 import DataSourcesServiceClient

        ds_client = DataSourcesServiceClient(credentials=self._get_credentials())
        try:
            data_sources = ds_client.list_data_sources(parent=self._parent)
            for ds in data_sources:
                if hasattr(ds, 'primary_product_data_source') and ds.primary_product_data_source:
                    data_source_name = ds.name
                    frappe.db.set_value(
                        "Catalog Platform", self.platform.name,
                        "google_data_source", data_source_name,
                    )
                    frappe.db.commit()
                    return data_source_name
        except Exception:
            frappe.log_error(
                title="Catalog Bridge: failed to auto-detect Google data source",
                message=frappe.get_traceback(),
            )

        frappe.throw(
            "Could not find an API data source in your Merchant Center account. "
            "Please create one in Merchant Center > Products > Feeds > Add feed (API), "
            "then set the Data Source field on this platform."
        )

    def push(self, product_data: dict) -> dict:
        """Upsert a product to Google Merchant Center using type registry."""
        from google.shopping.merchant_products_v1 import (
            InsertProductInputRequest,
            ProductInput,
        )
        from google.shopping.merchant_products_v1.types import ProductAttributes

        client = self._get_product_inputs_client()
        data_source = self._get_data_source()

        # Work on a copy so we don't mutate the caller's dict
        data = dict(product_data)
        offer_id = data.pop("offer_id", None)
        content_language = data.pop("content_language", self._content_language)
        feed_label = data.pop("feed_label", self._feed_label)

        attrs = {}

        # Process complex fields via type registry
        for _name, spec in COMPLEX_FIELD_BUILDERS.items():
            if any(k in data for k in spec["keys"]):
                result = spec["builder"](data)
                if result is not None:
                    attrs[spec["attr"]] = result

        # GTIN / MPN — pass through if present
        if data.get("gtin"):
            attrs["gtins"] = [data.pop("gtin")]
        if data.get("mpn"):
            attrs["mpn"] = data.pop("mpn")

        # All remaining keys pass through as simple attributes
        skip_keys = {"gtin", "mpn"}
        for key, value in data.items():
            if key in skip_keys:
                continue
            if value is not None and value != "":
                attrs[key] = value

        product_input = ProductInput(
            offer_id=offer_id,
            content_language=content_language,
            feed_label=feed_label,
            product_attributes=ProductAttributes(**attrs),
        )

        request = InsertProductInputRequest(
            parent=self._parent,
            product_input=product_input,
            data_source=data_source,
        )

        response = client.insert_product_input(request=request)
        return {"name": response.name, "offer_id": offer_id}

    def delete(self, retailer_id: str) -> dict:
        """Delete a product from Google Merchant Center."""
        from google.shopping.merchant_products_v1 import DeleteProductInputRequest

        client = self._get_product_inputs_client()
        data_source = self._get_data_source()

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
        """Fetch all products from Google Merchant Center with full details."""
        client = self._get_products_client()
        products = []

        try:
            response = client.list_products(parent=self._parent)
            for product in response:
                products.append(self._parse_product(product))
        except Exception:
            frappe.log_error(
                title="Catalog Bridge: Google list_products failed",
                message=frappe.get_traceback(),
            )

        return products

    def _parse_product(self, product) -> dict:
        """Extract all useful fields from a Google Product proto."""
        import json

        attrs = product.product_attributes
        status = product.product_status

        data = {
            "offer_id": product.offer_id or "",
            "retailer_id": product.offer_id or "",
            "google_product_name": product.name,
            "title": attrs.title if attrs else "",
            "description": attrs.description if attrs else "",
            "link": attrs.link if attrs else "",
            "image_link": attrs.image_link if attrs else "",
            "brand": attrs.brand if attrs else "",
            "condition": str(attrs.condition).replace("Condition.", "") if attrs and attrs.condition else "",
            "availability": str(attrs.availability).replace("Availability.", "") if attrs and attrs.availability else "",
            "product_types": list(attrs.product_types) if attrs and attrs.product_types else [],
        }

        if attrs and attrs.price and attrs.price.amount_micros:
            amount = attrs.price.amount_micros / 1_000_000
            currency = attrs.price.currency_code or "INR"
            data["price"] = f"{amount:.2f} {currency}"
        else:
            data["price"] = ""

        data["google_status"] = "Unknown"
        destination_statuses = []
        if status and status.destination_statuses:
            for ds in status.destination_statuses:
                ds_dict = {
                    "reporting_context": str(ds.reporting_context) if ds.reporting_context else "",
                    "approved_countries": list(ds.approved_countries) if ds.approved_countries else [],
                    "pending_countries": list(ds.pending_countries) if ds.pending_countries else [],
                    "disapproved_countries": list(ds.disapproved_countries) if ds.disapproved_countries else [],
                }
                destination_statuses.append(ds_dict)

                if ds_dict["disapproved_countries"]:
                    data["google_status"] = "Disapproved"
                elif ds_dict["pending_countries"] and data["google_status"] != "Disapproved":
                    data["google_status"] = "Pending"
                elif ds_dict["approved_countries"] and data["google_status"] not in ("Disapproved", "Pending"):
                    data["google_status"] = "Approved"

        data["destination_statuses_raw"] = json.dumps(destination_statuses)

        issues = []
        if status and status.item_level_issues:
            for issue in status.item_level_issues:
                issues.append({
                    "code": issue.code or "",
                    "severity": str(issue.severity).replace("Severity.", "") if issue.severity else "",
                    "description": issue.description or "",
                    "detail": issue.detail or "",
                    "attribute": issue.attribute or "",
                    "documentation": issue.documentation or "",
                })
        data["issues"] = json.dumps(issues)

        return data

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
        """Push products one at a time with rate limiting."""
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

"""Base connector interface for catalog platforms."""

import json
import time

import frappe
from frappe.utils import strip_html


# Default field mappings per platform type
GOOGLE_MERCHANT_DEFAULTS = [
    {"source": "item_code", "target": "offer_id", "is_id": True},
    {"source": "web_item_name", "target": "title", "fallback": "item_name"},
    {"source": "description", "target": "description", "transform": "strip_html", "fallback": "web_long_description"},
    {"source": "$url", "target": "link"},
    {"source": "$image", "target": "image_link"},
    {"source": "brand", "target": "brand"},
    {"source": "$const:NEW", "target": "condition"},
    {"source": "item_group", "target": "product_types", "transform": "wrap_list"},
    {"source": "$price", "target": "price_amount_micros", "config": {"multiplier": 1000000}, "update_group": "price"},
    {"source": "$price_currency", "target": "price_currency", "default": "INR", "update_group": "price"},
    {"source": "$availability", "target": "availability", "default": "IN_STOCK", "config": {"in_stock": "IN_STOCK", "out_of_stock": "OUT_OF_STOCK"}, "update_group": "availability"},
    {"source": "item.weight_per_unit", "target": "shipping_weight_value", "default": 0.5},
    {"source": "item.weight_uom", "target": "shipping_weight_unit", "transform": "uom_to_weight_unit", "default": "kg"},
]

META_CATALOG_DEFAULTS = [
    {"source": "item_code", "target": "retailer_id", "is_id": True},
    {"source": "web_item_name", "target": "name", "fallback": "item_name"},
    {"source": "description", "target": "description", "transform": "strip_html", "fallback": "web_long_description"},
    {"source": "short_description", "target": "short_description"},
    {"source": "$url", "target": "url"},
    {"source": "$image", "target": "image_url"},
    {"source": "brand", "target": "brand"},
    {"source": "item_group", "target": "category"},
    {"source": "$price", "target": "price", "config": {"multiplier": 100}, "update_group": "price"},
    {"source": "$price_currency", "target": "currency", "default": "INR", "update_group": "price"},
    {"source": "$availability", "target": "availability", "default": "in stock", "config": {"in_stock": "in stock", "out_of_stock": "out of stock"}, "update_group": "availability"},
]

PLATFORM_DEFAULTS = {
    "Google Merchant Center": GOOGLE_MERCHANT_DEFAULTS,
    "Meta Catalog": META_CATALOG_DEFAULTS,
}

# Known transforms — validated on Catalog Platform save
KNOWN_TRANSFORMS = {"strip_html", "wrap_list", "uom_to_weight_unit"}

# UOM normalization map (ERPNext UOM name -> Google/standard weight unit)
UOM_MAP = {
    "kg": "kg", "Kg": "kg", "KG": "kg", "kilogram": "kg", "Kilogram": "kg",
    "g": "g", "Gram": "g", "gram": "g", "gm": "g",
    "lb": "lb", "Lb": "lb", "lbs": "lb", "pound": "lb", "Pound": "lb",
    "oz": "oz", "Oz": "oz", "ounce": "oz", "Ounce": "oz",
}


class CatalogConnector:
    """Base class for platform connectors with JSON-driven field mapping."""

    def __init__(self, platform_doc):
        self.platform = platform_doc
        self._mapping = None

    def _get_mapping(self):
        """Load the field mapping JSON from the platform doc, or use defaults."""
        if self._mapping is not None:
            return self._mapping

        raw = self.platform.field_mapping
        if raw and isinstance(raw, str):
            try:
                self._mapping = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                frappe.throw("Invalid JSON in Field Mapping. Please fix it or clear the field to use defaults.")
        elif raw and isinstance(raw, list):
            # Already parsed (e.g. in tests)
            self._mapping = raw
        else:
            self._mapping = PLATFORM_DEFAULTS.get(self.platform.platform_type, [])

        return self._mapping

    def get_id_field(self):
        """Return the target field name marked as is_id in the mapping."""
        for entry in self._get_mapping():
            if entry.get("is_id"):
                return entry["target"]
        # Fallback based on platform type
        if self.platform.platform_type == "Google Merchant Center":
            return "offer_id"
        return "retailer_id"

    def transform(self, website_item) -> dict:
        """Transform Website Item fields to platform format using JSON mapping."""
        wi = website_item
        if isinstance(wi, str):
            wi = frappe.get_doc("Website Item", wi)

        mapping = self._get_mapping()
        product_data = {}

        for entry in mapping:
            value = self._resolve_source(entry, wi)

            if value is None and entry.get("fallback"):
                value = getattr(wi, entry["fallback"], None)
                if value == "" or value is None:
                    value = None

            if value is None and "default" in entry:
                value = entry["default"]

            if value is None:
                continue

            if entry.get("transform"):
                value = self._apply_transform(value, entry["transform"], entry.get("config"))

            product_data[entry["target"]] = value

        # Always include content_language and feed_label for Google
        if self.platform.platform_type == "Google Merchant Center":
            product_data["content_language"] = self.platform.google_content_language or "en"
            product_data["feed_label"] = self.platform.google_feed_label or "online"

        return product_data

    def filter_for_update(self, product_data, fields_changed):
        """Trim product_data to only include fields in the changed update_groups.

        Args:
            product_data: Full transformed product dict.
            fields_changed: List of update_group names that changed (e.g. ["price"]).

        Returns:
            Trimmed dict with ID field + only fields belonging to changed groups.
        """
        if not fields_changed:
            return product_data

        mapping = self._get_mapping()
        id_field = self.get_id_field()
        trimmed = {}

        # Always include the ID field
        if id_field in product_data:
            trimmed[id_field] = product_data[id_field]

        # Always include content_language and feed_label for Google
        for key in ("content_language", "feed_label"):
            if key in product_data:
                trimmed[key] = product_data[key]

        # Build a set of target fields that belong to the changed groups
        target_fields = set()
        for entry in mapping:
            group = entry.get("update_group")
            if group and group in fields_changed:
                target_fields.add(entry["target"])

        # Also include any fields_changed that aren't update_groups (direct field names)
        for field in fields_changed:
            if field in product_data:
                target_fields.add(field)

        for key in target_fields:
            if key in product_data:
                trimmed[key] = product_data[key]

        return trimmed

    def _resolve_source(self, entry, wi):
        """Resolve a mapping entry's source to a value."""
        source = entry.get("source", "")
        config = entry.get("config", {})

        # Static constant: $const:VALUE
        if source.startswith("$const:"):
            return source[7:]

        # Computed: $price
        if source == "$price":
            rate, _currency = self._get_price(wi.item_code)
            if rate is None:
                return None
            multiplier = config.get("multiplier", 1)
            return int(float(rate) * multiplier)

        # Computed: $price_currency
        if source == "$price_currency":
            _rate, currency = self._get_price(wi.item_code)
            return currency

        # Computed: $availability
        if source == "$availability":
            in_stock = self._get_availability(wi)
            if in_stock is None:
                return None
            in_stock_str = config.get("in_stock", "in stock")
            out_of_stock_str = config.get("out_of_stock", "out of stock")
            return in_stock_str if in_stock else out_of_stock_str

        # Computed: $url
        if source == "$url":
            return self._build_product_url(wi)

        # Computed: $image
        if source == "$image":
            return self._build_image_url(wi)

        # Cross-doctype: "item.field_name" via wi.item_code
        if "." in source:
            docfield_parts = source.split(".", 1)
            linked_doctype = docfield_parts[0]
            field_name = docfield_parts[1]

            if linked_doctype == "item":
                val = frappe.db.get_value("Item", wi.item_code, field_name)
                if val is None or val == "" or val == 0:
                    return None
                return val
            return None

        # Direct field from Website Item
        val = getattr(wi, source, None)
        if val == "" or val is None:
            return None
        return val

    def _apply_transform(self, value, transform_name, config=None):
        """Apply a named transform to a value."""
        if transform_name == "strip_html":
            return strip_html(str(value))

        if transform_name == "wrap_list":
            if isinstance(value, list):
                return value
            return [value]

        if transform_name == "uom_to_weight_unit":
            return UOM_MAP.get(str(value), str(value).lower())

        # Unknown transform — log warning, pass through
        frappe.logger().warning(f"Catalog Bridge: unknown transform '{transform_name}', passing value through")
        return value

    def _get_price(self, item_code):
        """Get price from the configured price list. Returns (rate, currency) tuple."""
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
            return None, None
        return price_row.price_list_rate, price_row.currency

    def _get_availability(self, website_item):
        """Get stock availability from Bin. Returns True (in stock), False (out of stock), or None."""
        if not website_item.website_warehouse:
            return None

        qty = frappe.db.get_value(
            "Bin",
            {"item_code": website_item.item_code, "warehouse": website_item.website_warehouse},
            "actual_qty",
        )
        if qty is None:
            return False
        return float(qty) > 0

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

    def push(self, product_data: dict) -> dict:
        raise NotImplementedError

    def delete(self, retailer_id: str) -> dict:
        raise NotImplementedError

    def list_products(self) -> list[dict]:
        raise NotImplementedError

    def get_product(self, retailer_id: str) -> dict:
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

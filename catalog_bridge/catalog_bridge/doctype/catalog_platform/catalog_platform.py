"""Catalog Platform — settings per platform instance."""

import json

import frappe
from frappe.model.document import Document

from catalog_bridge.connectors.base import KNOWN_TRANSFORMS, PLATFORM_DEFAULTS


class CatalogPlatform(Document):
    def validate(self):
        if self.platform_type == "Meta Catalog":
            if not self.whatsapp_account:
                frappe.throw("WhatsApp Account is required for Meta Catalog.")
            if not self.catalog_id:
                frappe.throw("Catalog ID is required for Meta Catalog.")

        if self.platform_type == "Google Merchant Center":
            if not self.google_service_account_json:
                frappe.throw("Service Account JSON is required for Google Merchant Center.")
            if not self.google_merchant_id:
                frappe.throw("Merchant ID is required for Google Merchant Center.")

        if not self.price_list:
            frappe.throw("Price List is required.")

        # Validate Jinja templates
        self._validate_template("product_url_template")
        self._validate_template("image_url_template")

        # Validate field mapping JSON
        self._validate_field_mapping()

    def before_insert(self):
        """Pre-populate field mapping with platform defaults if empty."""
        if not self.field_mapping and self.platform_type:
            defaults = PLATFORM_DEFAULTS.get(self.platform_type)
            if defaults:
                self.field_mapping = json.dumps(defaults, indent=2)

    def _validate_template(self, field):
        template = self.get(field)
        if not template:
            return
        try:
            frappe.render_template(template, {
                "frontend_url": "https://example.com",
                "route": "test-product",
                "item_code": "TEST-001",
                "item_name": "Test",
                "name": "TEST-001",
                "web_item_name": "Test Product",
                "website_image": "/files/test.jpg",
            })
        except Exception as e:
            frappe.throw(
                f"Invalid Jinja template in {frappe.bold(self.meta.get_label(field))}: {e}"
            )

    def _validate_field_mapping(self):
        """Validate the field mapping JSON structure and transform names."""
        raw = self.field_mapping
        if not raw:
            return

        try:
            mapping = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            frappe.throw(f"Invalid JSON in Field Mapping: {e}")

        if not isinstance(mapping, list):
            frappe.throw("Field Mapping must be a JSON array.")

        has_id = False
        for i, entry in enumerate(mapping):
            if not isinstance(entry, dict):
                frappe.throw(f"Field Mapping entry {i + 1} must be a JSON object.")

            if not entry.get("source"):
                frappe.throw(f"Field Mapping entry {i + 1} is missing 'source'.")
            if not entry.get("target"):
                frappe.throw(f"Field Mapping entry {i + 1} is missing 'target'.")

            if entry.get("is_id"):
                has_id = True

            transform = entry.get("transform")
            if transform and transform not in KNOWN_TRANSFORMS:
                frappe.throw(
                    f"Field Mapping entry {i + 1}: unknown transform '{transform}'. "
                    f"Valid transforms: {', '.join(sorted(KNOWN_TRANSFORMS))}"
                )

        if not has_id:
            frappe.msgprint(
                "No entry has is_id: true. The connector will use a platform-type default ID field.",
                indicator="orange",
                alert=True,
            )

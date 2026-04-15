"""Catalog Platform — settings per platform instance."""

import frappe
from frappe.model.document import Document


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

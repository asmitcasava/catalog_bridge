"""Core sync logic — transform, push, and log."""

import json

import frappe
from frappe.utils import now_datetime

from catalog_bridge.connectors.base import get_connector


def sync_item(website_item, platform, fields_changed=None):
    """Sync a single Website Item to a platform.

    Args:
        website_item: Name of the Website Item doc.
        platform: Name of the Catalog Platform doc.
        fields_changed: Optional list of field names that changed.
            If provided, only those fields are included in the push payload.
    """
    try:
        wi = frappe.get_doc("Website Item", website_item)
    except frappe.DoesNotExistError:
        return

    # Skip template/parent items with no warehouse — they have no price or stock
    if not wi.website_warehouse:
        return

    platform_doc = frappe.get_doc("Catalog Platform", platform)
    if not platform_doc.enabled:
        return

    connector = get_connector(platform_doc)

    # Determine action: Create if no prior successful sync, else Update
    has_prior = frappe.db.exists("Catalog Sync Log", {
        "website_item": website_item,
        "platform": platform,
        "status": "Success",
    })
    action = "Update" if has_prior else "Create"

    # Create sync log entry
    log = frappe.new_doc("Catalog Sync Log")
    log.website_item = website_item
    log.platform = platform
    log.action = action
    log.status = "Queued"
    log.insert(ignore_permissions=True)
    frappe.db.commit()

    try:
        product_data = connector.transform(wi)

        # If only specific fields changed, trim the payload using mapping-aware filtering
        if fields_changed and action == "Update":
            product_data = connector.filter_for_update(product_data, fields_changed)

        log.request_data = json.dumps(product_data, default=str)
        response = connector.push(product_data)
        log.response_data = json.dumps(response, default=str) if response else ""
        log.status = "Success"
        log.synced_at = now_datetime()

        # Update platform last_synced
        frappe.db.set_value("Catalog Platform", platform, "last_synced", now_datetime())

    except Exception as e:
        log.status = "Failed"
        log.error_message = str(e)[:500]
        frappe.log_error(
            title=f"Catalog Bridge: sync {website_item} to {platform}",
            message=frappe.get_traceback(),
        )

    log.save(ignore_permissions=True)
    frappe.db.commit()


def delete_item(website_item, platform):
    """Delete a product from a platform.

    Only deletes if the product was previously synced successfully.
    """
    # Delete guard: skip if never successfully synced
    has_prior = frappe.db.exists("Catalog Sync Log", {
        "website_item": website_item,
        "platform": platform,
        "status": "Success",
    })
    if not has_prior:
        return

    platform_doc = frappe.get_doc("Catalog Platform", platform)
    if not platform_doc.enabled:
        return

    connector = get_connector(platform_doc)

    # Get item_code for retailer_id
    item_code = frappe.db.get_value("Website Item", website_item, "item_code")
    if not item_code:
        return

    log = frappe.new_doc("Catalog Sync Log")
    log.website_item = website_item
    log.platform = platform
    log.action = "Delete"
    log.status = "Queued"
    log.insert(ignore_permissions=True)
    frappe.db.commit()

    try:
        response = connector.delete(item_code)
        log.response_data = json.dumps(response, default=str) if response else ""
        log.status = "Success"
        log.synced_at = now_datetime()
    except Exception as e:
        log.status = "Failed"
        log.error_message = str(e)[:500]
        frappe.log_error(
            title=f"Catalog Bridge: delete {website_item} from {platform}",
            message=frappe.get_traceback(),
        )

    log.save(ignore_permissions=True)
    frappe.db.commit()


def sync_item_to_all_platforms(website_item, fields_changed=None):
    """Enqueue sync to all enabled platforms with sync_on_save."""
    platforms = frappe.get_all(
        "Catalog Platform",
        filters={"enabled": 1, "sync_on_save": 1},
        pluck="name",
    )
    for platform in platforms:
        frappe.enqueue(
            "catalog_bridge.sync.sync_item",
            queue="short",
            enqueue_after_commit=True,
            website_item=website_item,
            platform=platform,
            fields_changed=fields_changed,
        )


def delete_item_from_all_platforms(website_item):
    """Enqueue delete from all enabled platforms."""
    platforms = frappe.get_all(
        "Catalog Platform",
        filters={"enabled": 1},
        pluck="name",
    )
    for platform in platforms:
        frappe.enqueue(
            "catalog_bridge.sync.delete_item",
            queue="short",
            enqueue_after_commit=True,
            website_item=website_item,
            platform=platform,
        )

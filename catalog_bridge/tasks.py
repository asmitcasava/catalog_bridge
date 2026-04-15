"""Scheduled tasks — retry, reconciliation, cleanup, initial sync."""

import json

import frappe
from frappe.utils import now_datetime, add_to_date

from catalog_bridge.connectors.base import get_connector
from catalog_bridge.events import rebuild_item_cache


# Backoff intervals in minutes for retries: attempt 1 = 5min, 2 = 15min, 3 = 45min
BACKOFF_MINUTES = [5, 15, 45]
MAX_RETRIES = 3


def retry_failed_syncs():
    """Retry failed sync log entries with exponential backoff.

    Runs every 5 minutes via scheduler. Only retries items whose
    backoff window has elapsed.
    """
    failed_logs = frappe.get_all(
        "Catalog Sync Log",
        filters={
            "status": ["in", ["Failed", "Retrying"]],
            "retry_count": ["<", MAX_RETRIES],
        },
        fields=["name", "website_item", "platform", "action", "retry_count", "synced_at", "modified"],
    )

    now = now_datetime()

    for log_entry in failed_logs:
        # Check backoff window
        retry_idx = min(log_entry.retry_count, len(BACKOFF_MINUTES) - 1)
        backoff_min = BACKOFF_MINUTES[retry_idx]
        last_attempt = log_entry.synced_at or log_entry.modified
        eligible_at = add_to_date(last_attempt, minutes=backoff_min)

        if now < eligible_at:
            continue

        # Update log status
        frappe.db.set_value("Catalog Sync Log", log_entry.name, {
            "status": "Retrying",
            "retry_count": log_entry.retry_count + 1,
        })
        frappe.db.commit()

        if log_entry.action == "Delete":
            frappe.enqueue(
                "catalog_bridge.sync.delete_item",
                queue="short",
                website_item=log_entry.website_item,
                platform=log_entry.platform,
            )
        else:
            frappe.enqueue(
                "catalog_bridge.sync.sync_item",
                queue="short",
                website_item=log_entry.website_item,
                platform=log_entry.platform,
            )

    # Mark permanently failed (exceeded max retries)
    perm_failed = frappe.get_all(
        "Catalog Sync Log",
        filters={
            "status": ["in", ["Failed", "Retrying"]],
            "retry_count": [">=", MAX_RETRIES],
        },
        fields=["name", "website_item", "platform"],
    )

    for log_entry in perm_failed:
        frappe.db.set_value("Catalog Sync Log", log_entry.name, "status", "Permanently Failed")

        # Send alert email
        platform_doc = frappe.get_doc("Catalog Platform", log_entry.platform)
        if platform_doc.alert_email:
            frappe.sendmail(
                recipients=[platform_doc.alert_email],
                subject=f"Catalog Sync Failed: {log_entry.website_item}",
                message=f"Sync for Website Item {log_entry.website_item} to "
                        f"{log_entry.platform} has permanently failed after "
                        f"{MAX_RETRIES} retries. Check the Catalog Sync Log for details.",
            )

    if perm_failed:
        frappe.db.commit()


def run_reconciliation():
    """Daily reconciliation: compare platform products against Website Items.

    For each enabled platform:
    1. Fetch all products from the platform
    2. Compare against published Website Items
    3. Push missing/stale items, flag orphans
    """
    # Rebuild Redis cache while we're at it
    rebuild_item_cache()

    platforms = frappe.get_all(
        "Catalog Platform",
        filters={"enabled": 1},
        pluck="name",
    )

    for platform_name in platforms:
        try:
            _reconcile_platform(platform_name)
        except Exception as e:
            frappe.log_error(
                "Catalog Bridge Reconciliation",
                f"Reconciliation failed for {platform_name}: {e}",
            )


def _reconcile_platform(platform_name):
    """Reconcile a single platform against Website Items."""
    platform_doc = frappe.get_doc("Catalog Platform", platform_name)
    connector = get_connector(platform_doc)

    # Fetch all products on platform
    platform_products = connector.list_products()
    platform_ids = {p.get("retailer_id") for p in platform_products}

    # Get all published Website Items
    website_items = frappe.get_all(
        "Website Item",
        filters={"published": 1},
        fields=["name", "item_code"],
    )
    local_ids = {wi.item_code for wi in website_items}
    item_name_map = {wi.item_code: wi.name for wi in website_items}

    # Missing: in ERPNext but not on platform
    missing = local_ids - platform_ids
    for item_code in missing:
        wi_name = item_name_map.get(item_code)
        if wi_name:
            frappe.enqueue(
                "catalog_bridge.sync.sync_item",
                queue="long",
                website_item=wi_name,
                platform=platform_name,
            )

    # Orphans: on platform but not in ERPNext (log for review)
    orphans = platform_ids - local_ids
    if orphans:
        frappe.log_error(
            "Catalog Bridge Reconciliation",
            f"Orphan products on {platform_name} (on platform but not in ERPNext): "
            f"{', '.join(list(orphans)[:20])}",
        )

    frappe.db.set_value("Catalog Platform", platform_name, "last_synced", now_datetime())
    frappe.db.commit()


def cleanup_old_sync_logs():
    """Delete successful sync logs older than 90 days."""
    cutoff = add_to_date(now_datetime(), days=-90)
    old_logs = frappe.get_all(
        "Catalog Sync Log",
        filters={
            "status": "Success",
            "synced_at": ["<", cutoff],
        },
        pluck="name",
        limit=1000,
    )
    for name in old_logs:
        frappe.delete_doc("Catalog Sync Log", name, ignore_permissions=True)

    if old_logs:
        frappe.db.commit()


@frappe.whitelist()
def initial_sync(platform_name):
    """One-time bulk sync of all published Website Items to a platform.

    Usage:
        bench execute catalog_bridge.tasks.initial_sync --kwargs '{"platform_name": "Meta Catalog"}'
    Or via the "Sync All Items" button on the Catalog Platform form.
    """
    platform_doc = frappe.get_doc("Catalog Platform", platform_name)
    if not platform_doc.enabled:
        frappe.throw(f"Platform {platform_name} is not enabled.")

    connector = get_connector(platform_doc)

    website_items = frappe.get_all(
        "Website Item",
        filters={"published": 1},
        fields=["name"],
    )

    products = []
    for wi_ref in website_items:
        try:
            wi = frappe.get_doc("Website Item", wi_ref.name)
            product_data = connector.transform(wi)
            products.append(product_data)
        except Exception as e:
            frappe.log_error("Catalog Bridge Initial Sync", f"Transform failed for {wi_ref.name}: {e}")

    if not products:
        return "No published Website Items found."

    results = connector.bulk_push(products)

    # Create sync logs for the bulk operation
    for wi_ref in website_items:
        log = frappe.new_doc("Catalog Sync Log")
        log.website_item = wi_ref.name
        log.platform = platform_name
        log.action = "Create"
        log.status = "Success"
        log.synced_at = now_datetime()
        log.insert(ignore_permissions=True)

    frappe.db.set_value("Catalog Platform", platform_name, "last_synced", now_datetime())
    frappe.db.commit()

    msg = f"Synced {results['success']} of {len(products)} products."
    if results["failed"]:
        msg += f" Failed: {results['failed']}."
    if results["errors"]:
        msg += f" Errors: {'; '.join(results['errors'][:5])}"

    return msg

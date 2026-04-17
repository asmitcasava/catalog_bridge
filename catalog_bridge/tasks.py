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
                title=f"Catalog Bridge: reconciliation failed for {platform_name}",
                message=frappe.get_traceback(),
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

    # Orphans: on platform but not in ERPNext — delete from platform
    _delete_orphans(connector, platform_name, platform_ids, local_ids)

    frappe.db.set_value("Catalog Platform", platform_name, "last_synced", now_datetime())
    frappe.db.commit()


def _delete_orphans(connector, platform_name, platform_ids, local_ids):
    """Delete products that exist on the platform but not in ERPNext.

    Args:
        connector: A CatalogConnector instance.
        platform_name: Name of the Catalog Platform doc.
        platform_ids: Set of retailer_ids currently on the platform.
        local_ids: Set of item_codes for published Website Items.

    Returns:
        dict with keys: deleted (int), failed (int), errors (list[str])
    """
    orphans = platform_ids - local_ids
    results = {"deleted": 0, "failed": 0, "errors": []}

    for item_code in orphans:
        if not item_code:
            continue
        try:
            connector.delete(item_code)
            results["deleted"] += 1
        except Exception as e:
            results["failed"] += 1
            results["errors"].append(f"{item_code}: {e}")
            frappe.log_error(
                title=f"Catalog Bridge: failed to delete orphan {item_code} from {platform_name}",
                message=frappe.get_traceback(),
            )

    # Clean up Google Product Feed records for deleted items
    if orphans:
        orphan_feeds = frappe.get_all(
            "Google Product Feed",
            filters={"offer_id": ["in", list(orphans)], "platform": platform_name},
            pluck="name",
        )
        for feed in orphan_feeds:
            frappe.delete_doc("Google Product Feed", feed, ignore_permissions=True)

    return results


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
def initial_sync(platform_name, delete_orphans=True):
    """Bulk two-way sync of all published Website Items to a platform.

    Pushes every published Website Item, then deletes orphan products
    (products on the platform whose Website Item no longer exists or
    is no longer published).

    Args:
        platform_name: Name of the Catalog Platform doc.
        delete_orphans: If True (default), remove products that exist on
            the platform but not in ERPNext. Pass False to push-only.

    Usage:
        bench execute catalog_bridge.tasks.initial_sync --kwargs '{"platform_name": "Meta Catalog"}'
    Or via the "Sync All Items" button on the Catalog Platform form.
    """
    platform_doc = frappe.get_doc("Catalog Platform", platform_name)
    if not platform_doc.enabled:
        frappe.throw(f"Platform {platform_name} is not enabled.")

    # Normalize the delete_orphans flag — Frappe whitelist passes strings from the client
    if isinstance(delete_orphans, str):
        delete_orphans = delete_orphans.lower() not in ("false", "0", "no", "")

    connector = get_connector(platform_doc)
    id_field = connector.get_id_field()

    website_items = frappe.get_all(
        "Website Item",
        filters={"published": 1},
        fields=["name", "item_code"],
    )
    local_ids = {wi.item_code for wi in website_items}

    # Step 1: Delete orphans before pushing, so the platform state is clean
    orphan_results = {"deleted": 0, "failed": 0, "errors": []}
    if delete_orphans:
        try:
            platform_products = connector.list_products()
            platform_ids = {p.get("retailer_id") for p in platform_products}
            orphan_results = _delete_orphans(connector, platform_name, platform_ids, local_ids)
        except Exception:
            frappe.log_error(
                title=f"Catalog Bridge: orphan fetch failed for {platform_name}",
                message=frappe.get_traceback(),
            )
            orphan_results["errors"].append("Orphan cleanup skipped — could not list platform products.")

    # Step 2: Transform every published Website Item
    products = []
    for wi_ref in website_items:
        try:
            wi = frappe.get_doc("Website Item", wi_ref.name)
            product_data = connector.transform(wi)
            products.append(product_data)
        except Exception:
            frappe.log_error(
                title=f"Catalog Bridge: transform failed for {wi_ref.name}",
                message=frappe.get_traceback(),
            )

    # Step 3: Push
    if products:
        results = connector.bulk_push(products)
    else:
        results = {"success": 0, "failed": 0, "errors": []}

    # Build a set of failed IDs for accurate sync log status
    failed_ids = set()
    for err in results.get("errors", []):
        if ":" in err:
            failed_ids.add(err.split(":")[0].strip())

    # Create sync logs per item with accurate status
    for wi_ref, product_data in zip(website_items, products):
        retailer_id = product_data.get(id_field, "")
        is_failed = retailer_id in failed_ids
        log = frappe.new_doc("Catalog Sync Log")
        log.website_item = wi_ref.name
        log.platform = platform_name
        log.action = "Create"
        log.status = "Failed" if is_failed else "Success"
        log.synced_at = now_datetime()
        log.request_data = json.dumps(product_data, default=str)
        if is_failed:
            for err in results["errors"]:
                if err.startswith(retailer_id):
                    log.error_message = err[:500]
                    break
        log.insert(ignore_permissions=True)

    frappe.db.set_value("Catalog Platform", platform_name, "last_synced", now_datetime())
    frappe.db.commit()

    if results["errors"]:
        frappe.log_error(
            title=f"Catalog Bridge: initial_sync to {platform_name}",
            message=(
                f"Failed {results['failed']} of {len(products)} products.\n\n"
                + "\n".join(results["errors"])
            ),
        )

    # Build user-facing summary
    parts = []
    if products:
        parts.append(f"Synced {results['success']} of {len(products)} products")
    else:
        parts.append("No published Website Items found")

    if delete_orphans:
        if orphan_results["deleted"]:
            parts.append(f"deleted {orphan_results['deleted']} orphan(s) from platform")
        elif not orphan_results["errors"]:
            parts.append("no orphans to delete")

    if results["failed"]:
        parts.append(f"{results['failed']} push failures")
    if orphan_results["failed"]:
        parts.append(f"{orphan_results['failed']} orphan-delete failures")

    msg = ". ".join(parts) + "."

    if results["errors"]:
        msg += f" Push errors: {'; '.join(results['errors'][:3])}"
    if orphan_results["errors"]:
        msg += f" Orphan errors: {'; '.join(orphan_results['errors'][:3])}"

    return msg


@frappe.whitelist()
def refresh_google_feed(platform_name):
    """Fetch all products from Google Merchant Center and update the feed doctype.

    On-demand only — triggered by the "Refresh Google Feed" button on the platform form.
    """
    platform_doc = frappe.get_doc("Catalog Platform", platform_name)
    if platform_doc.platform_type != "Google Merchant Center":
        frappe.throw("This action is only available for Google Merchant Center platforms.")

    connector = get_connector(platform_doc)
    products = connector.list_products()

    seen_offer_ids = set()
    counts = {"Approved": 0, "Disapproved": 0, "Pending": 0, "Unknown": 0}

    for p in products:
        offer_id = p.get("offer_id")
        if not offer_id:
            continue

        seen_offer_ids.add(offer_id)

        # Find matching Website Item by item_code
        wi_name = frappe.db.get_value("Website Item", {"item_code": offer_id}, "name")

        # Upsert Google Product Feed doc
        if frappe.db.exists("Google Product Feed", offer_id):
            doc = frappe.get_doc("Google Product Feed", offer_id)
        else:
            doc = frappe.new_doc("Google Product Feed")
            doc.offer_id = offer_id

        doc.platform = platform_name
        doc.website_item = wi_name or ""
        doc.title = p.get("title", "")
        doc.link = p.get("link", "")
        doc.image_link = p.get("image_link", "")
        doc.price = p.get("price", "")
        doc.availability = p.get("availability", "")
        doc.condition = p.get("condition", "")
        doc.brand = p.get("brand", "")
        doc.google_status = p.get("google_status", "Unknown")
        doc.issues = p.get("issues", "[]")
        doc.google_product_name = p.get("google_product_name", "")
        doc.destination_statuses_raw = p.get("destination_statuses_raw", "[]")
        doc.last_fetched = now_datetime()
        doc.save(ignore_permissions=True)

        status = doc.google_status
        if status in counts:
            counts[status] += 1

    # Mark products in DB but not in Google as "Removed"
    existing = frappe.get_all(
        "Google Product Feed",
        filters={"platform": platform_name},
        pluck="offer_id",
    )
    for oid in existing:
        if oid not in seen_offer_ids:
            frappe.db.set_value("Google Product Feed", oid, "google_status", "Removed")

    frappe.db.commit()

    parts = [f"Refreshed {len(products)} products"]
    for status, count in counts.items():
        if count:
            parts.append(f"{count} {status.lower()}")
    return ". ".join(parts) + "."

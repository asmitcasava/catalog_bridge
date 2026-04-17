"""Doc event handlers for Website Item, Item Price, and Bin."""

import frappe

from catalog_bridge.sync import sync_item_to_all_platforms, delete_item_from_all_platforms

CACHE_KEY = "catalog_bridge_items"


def on_website_item_update(doc, method):
    """Website Item saved — sync to all platforms."""
    _update_item_cache(doc)

    if not doc.published:
        # If was previously published and now unpublished, delete from platforms
        old = doc.get_doc_before_save()
        if old and old.published:
            delete_item_from_all_platforms(doc.name)
        return

    sync_item_to_all_platforms(doc.name)


def on_website_item_trash(doc, method):
    """Website Item trashed — delete from all platforms and clean up linked records."""
    _clear_item_cache(doc)

    # Delete linked records so Frappe's link check doesn't block
    for dt in ("Google Product Feed", "Catalog Sync Log"):
        linked = frappe.get_all(dt, filters={"website_item": doc.name}, pluck="name")
        for name in linked:
            frappe.delete_doc(dt, name, ignore_permissions=True)

    if doc.published:
        delete_item_from_all_platforms(doc.name)


def on_item_price_update(doc, method):
    """Item Price changed — sync matching Website Items."""
    # Find platforms using this price list
    platforms = frappe.get_all(
        "Catalog Platform",
        filters={"enabled": 1, "sync_on_save": 1, "price_list": doc.price_list},
        pluck="name",
    )
    if not platforms:
        return

    # Find published Website Items with this item_code
    website_items = frappe.get_all(
        "Website Item",
        filters={"item_code": doc.item_code, "published": 1},
        pluck="name",
    )

    for wi_name in website_items:
        for platform in platforms:
            frappe.enqueue(
                "catalog_bridge.sync.sync_item",
                queue="short",
                enqueue_after_commit=True,
                website_item=wi_name,
                platform=platform,
                fields_changed=["price"],
            )


def on_item_price_trash(doc, method):
    """Item Price deleted — sync matching Website Items (price removed)."""
    on_item_price_update(doc, method)


def on_bin_update(doc, method):
    """Bin updated (stock change) — sync if availability flipped.

    This is the hottest path. Bin updates on every stock transaction.
    Uses Redis cache for O(1) check of whether this item+warehouse is relevant.
    Only syncs when availability actually changes (qty crosses zero).
    """
    # Step 1: Redis check — is this item+warehouse pair published?
    pair_key = f"{doc.item_code}:{doc.warehouse}"
    cached = frappe.cache().hget(CACHE_KEY, pair_key)
    if not cached:
        return

    # Step 2: Did availability actually flip?
    old = doc.get_doc_before_save()
    if old:
        old_qty = float(old.actual_qty or 0)
        new_qty = float(doc.actual_qty or 0)
        old_available = old_qty > 0
        new_available = new_qty > 0
        if old_available == new_available:
            return
    # If no old doc (first Bin creation), always sync

    # Step 3: Find Website Items for this item+warehouse
    website_items = frappe.get_all(
        "Website Item",
        filters={
            "item_code": doc.item_code,
            "website_warehouse": doc.warehouse,
            "published": 1,
        },
        pluck="name",
    )

    for wi_name in website_items:
        sync_item_to_all_platforms(wi_name, fields_changed=["availability"])


def _update_item_cache(doc):
    """Update Redis cache of published (item_code, warehouse) pairs."""
    if not doc.item_code:
        return
    pair_key = f"{doc.item_code}:{doc.website_warehouse or ''}"
    if doc.published and doc.website_warehouse:
        frappe.cache().hset(CACHE_KEY, pair_key, "1")
    else:
        frappe.cache().hdel(CACHE_KEY, pair_key)


def _clear_item_cache(doc):
    """Remove item from cache on trash."""
    if doc.item_code and doc.website_warehouse:
        pair_key = f"{doc.item_code}:{doc.website_warehouse}"
        frappe.cache().hdel(CACHE_KEY, pair_key)


def rebuild_item_cache():
    """Rebuild the full Redis cache. Called on install and by reconciliation."""
    frappe.cache().delete_key(CACHE_KEY)
    items = frappe.get_all(
        "Website Item",
        filters={"published": 1},
        fields=["item_code", "website_warehouse"],
    )
    for item in items:
        if item.item_code and item.website_warehouse:
            pair_key = f"{item.item_code}:{item.website_warehouse}"
            frappe.cache().hset(CACHE_KEY, pair_key, "1")

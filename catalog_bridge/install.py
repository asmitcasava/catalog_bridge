"""Post-install hooks for catalog_bridge."""

import frappe


def after_install():
    """Rebuild Redis cache of published Website Item + warehouse pairs."""
    try:
        from catalog_bridge.events import rebuild_item_cache
        rebuild_item_cache()
    except Exception:
        pass

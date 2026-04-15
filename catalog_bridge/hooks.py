app_name = "catalog_bridge"
app_title = "Catalog Bridge"
app_publisher = "Casava Tech"
app_description = "Sync Website Items to Meta Catalog and Google Merchant Center"
app_email = "admin@casava.tech"
app_license = "mit"

required_apps = ["frappe/frappe_whatsapp", "frappe/webshop"]

doc_events = {
    "Website Item": {
        "on_update": "catalog_bridge.events.on_website_item_update",
        "on_trash": "catalog_bridge.events.on_website_item_trash",
    },
    "Item Price": {
        "on_update": "catalog_bridge.events.on_item_price_update",
        "on_trash": "catalog_bridge.events.on_item_price_trash",
    },
    "Bin": {
        "on_update": "catalog_bridge.events.on_bin_update",
    },
}

scheduler_events = {
    "cron": {
        "*/5 * * * *": [
            "catalog_bridge.tasks.retry_failed_syncs",
        ],
    },
    "daily": [
        "catalog_bridge.tasks.run_reconciliation",
        "catalog_bridge.tasks.cleanup_old_sync_logs",
    ],
}

after_install = "catalog_bridge.install.after_install"

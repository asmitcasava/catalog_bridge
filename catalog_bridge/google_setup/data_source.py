"""List and detect API data sources in Merchant Center."""

import frappe


@frappe.whitelist()
def detect_data_sources(platform_name):
    """List available API data sources for this merchant account.

    Returns dict with:
        data_sources (list[dict]): Each with name, display_name, type.
        recommended (str|None): Name of the recommended data source.
        error (str|None): Error message if the call failed.
    """
    platform = frappe.get_doc("Catalog Platform", platform_name)

    if not platform.google_service_account_json or not platform.google_merchant_id:
        return {"data_sources": [], "error": "Service account or Merchant ID not configured."}

    try:
        from google.oauth2 import service_account
        from google.shopping.merchant_datasources_v1 import DataSourcesServiceClient

        file_doc = frappe.get_doc("File", {"file_url": platform.google_service_account_json})
        file_path = file_doc.get_full_path()
        credentials = service_account.Credentials.from_service_account_file(file_path)

        client = DataSourcesServiceClient(credentials=credentials)
        parent = f"accounts/{platform.google_merchant_id}"
        response = client.list_data_sources(parent=parent)

        data_sources = []
        recommended = None

        for ds in response:
            is_primary = (
                hasattr(ds, "primary_product_data_source")
                and ds.primary_product_data_source
            )
            ds_info = {
                "name": ds.name,
                "display_name": getattr(ds, "display_name", "") or ds.name,
                "type": "PRIMARY_PRODUCT_DATA_SOURCE" if is_primary else "other",
            }
            data_sources.append(ds_info)

            # Recommend the first primary product data source
            if is_primary and not recommended:
                recommended = ds.name

        return {
            "data_sources": data_sources,
            "recommended": recommended,
        }

    except Exception as e:
        return {"data_sources": [], "error": str(e)}

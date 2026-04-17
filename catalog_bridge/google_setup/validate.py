"""Validate service account JSON and test Merchant Center access."""

import json

import frappe


@frappe.whitelist()
def validate_service_account(json_file_url):
    """Parse a service-account JSON file and validate its structure.

    Args:
        json_file_url: Frappe File URL of the uploaded JSON key.

    Returns dict with:
        valid (bool), project_id, client_email, error (str|None).
    """
    try:
        file_doc = frappe.get_doc("File", {"file_url": json_file_url})
        file_path = file_doc.get_full_path()

        with open(file_path) as f:
            data = json.load(f)

        required_keys = ["type", "project_id", "client_email", "private_key"]
        missing = [k for k in required_keys if k not in data]
        if missing:
            return {
                "valid": False,
                "error": f"Missing required fields: {', '.join(missing)}. "
                         "Make sure you uploaded a Service Account key (not an OAuth client JSON).",
            }

        if data.get("type") != "service_account":
            return {
                "valid": False,
                "error": f"Expected type 'service_account', got '{data.get('type')}'. "
                         "Download the JSON key from IAM > Service Accounts > Keys.",
            }

        return {
            "valid": True,
            "project_id": data["project_id"],
            "client_email": data["client_email"],
        }

    except json.JSONDecodeError:
        return {"valid": False, "error": "The uploaded file is not valid JSON."}
    except Exception as e:
        return {"valid": False, "error": str(e)}


@frappe.whitelist()
def test_merchant_access(platform_name):
    """Attempt list_data_sources with the configured service account.

    Returns dict with:
        status: "success" | "gcp_not_registered" | "permission_denied" | "error"
        data_sources: list of data source dicts (on success)
        error: error message (on failure)
    """
    platform = frappe.get_doc("Catalog Platform", platform_name)

    if not platform.google_service_account_json:
        return {"status": "error", "error": "Service Account JSON is not configured."}
    if not platform.google_merchant_id:
        return {"status": "error", "error": "Merchant ID is not configured."}

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
        for ds in response:
            ds_info = {"name": ds.name, "display_name": getattr(ds, "display_name", "")}
            if hasattr(ds, "primary_product_data_source") and ds.primary_product_data_source:
                ds_info["type"] = "PRIMARY_PRODUCT_DATA_SOURCE"
            else:
                ds_info["type"] = "other"
            data_sources.append(ds_info)

        return {"status": "success", "data_sources": data_sources}

    except Exception as e:
        error_str = str(e)
        if "GCP_NOT_REGISTERED" in error_str:
            return {
                "status": "gcp_not_registered",
                "error": "Your GCP project is not registered with this Merchant Center account. "
                         "Proceed to the registration step.",
            }
        if "PERMISSION_DENIED" in error_str or "403" in error_str:
            return {
                "status": "permission_denied",
                "error": "The service account does not have access to this Merchant Center. "
                         "Add it as an Admin user in Merchant Center > Settings > Access.",
            }
        return {"status": "error", "error": error_str}

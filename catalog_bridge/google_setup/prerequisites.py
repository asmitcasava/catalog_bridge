"""Check whether required Google packages are installed."""

import frappe


REQUIRED_PACKAGES = [
    ("google.oauth2", "google-auth"),
    ("google.shopping.merchant_products_v1", "google-shopping-merchant-products"),
    ("google.shopping.merchant_datasources_v1", "google-shopping-merchant-datasources"),
    ("google_auth_oauthlib", "google-auth-oauthlib"),
]


@frappe.whitelist()
def check_prerequisites():
    """Check if Google packages are installed.

    Returns dict with:
        all_installed (bool): True if every required package is importable.
        packages (list[dict]): Per-package status.
        install_command (str): bench pip install command for missing packages.
    """
    results = []
    missing = []

    for module_path, pip_name in REQUIRED_PACKAGES:
        try:
            __import__(module_path)
            results.append({"package": pip_name, "installed": True})
        except ImportError:
            results.append({"package": pip_name, "installed": False})
            missing.append(pip_name)

    install_cmd = ""
    if missing:
        install_cmd = "bench pip install " + " ".join(missing)

    return {
        "all_installed": len(missing) == 0,
        "packages": results,
        "install_command": install_cmd,
    }

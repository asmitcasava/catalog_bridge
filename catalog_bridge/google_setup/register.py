"""OAuth flow and GCP project registration with Merchant Center."""

import frappe

SCOPES = ["https://www.googleapis.com/auth/content"]


@frappe.whitelist()
def get_oauth_url(platform_name, client_id, client_secret, flow_type="desktop"):
    """Generate OAuth authorization URL for the registerGcp flow.

    Args:
        platform_name: Catalog Platform document name.
        client_id: OAuth client ID (not stored).
        client_secret: OAuth client secret (not stored).
        flow_type: "desktop" (manual code paste) or "web" (redirect callback).

    Returns dict with:
        auth_url (str): URL to open in the browser.
        state (str): CSRF state token (for web flow).
    """
    platform = frappe.get_doc("Catalog Platform", platform_name)

    if flow_type == "web":
        site_url = frappe.utils.get_url()
        redirect_uri = f"{site_url}/api/method/catalog_bridge.google_setup.oauth_callback.handle"
    else:
        redirect_uri = "urn:ietf:wg:oauth:2.0:oob"

    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(
        {
            "installed" if flow_type == "desktop" else "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
    )
    flow.redirect_uri = redirect_uri

    state = frappe.generate_hash(length=20)
    # Store state + flow config in cache for verification (5 min TTL)
    frappe.cache.set_value(
        f"gmc_oauth_state_{frappe.session.user}",
        {
            "state": state,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "flow_type": flow_type,
            "platform_name": platform_name,
        },
        expires_in_sec=300,
    )

    # Store state→user mapping so the OAuth callback can find the user
    # (callback is allow_guest and has no session context)
    frappe.cache.set_value(
        f"gmc_oauth_state_lookup_{state}",
        frappe.session.user,
        expires_in_sec=300,
    )

    auth_url, _ = flow.authorization_url(
        prompt="consent",
        access_type="offline",
        state=state,
    )

    return {"auth_url": auth_url, "state": state}


@frappe.whitelist()
def complete_registration(platform_name, auth_code, client_id, client_secret):
    """Exchange auth code for token and call registerGcp.

    Args:
        platform_name: Catalog Platform document name.
        auth_code: Authorization code from Google.
        client_id: OAuth client ID.
        client_secret: OAuth client secret.

    Returns dict with:
        success (bool), message (str), error (str|None).
    """
    import requests
    from google_auth_oauthlib.flow import Flow

    platform = frappe.get_doc("Catalog Platform", platform_name)
    merchant_id = platform.google_merchant_id

    if not merchant_id:
        return {"success": False, "error": "Merchant ID is not configured on the platform."}

    # Exchange code for token
    flow = Flow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
    )
    flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"

    try:
        flow.fetch_token(code=auth_code)
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to exchange authorization code: {e}. "
                     "The code may have expired — try authorizing again.",
        }

    access_token = flow.credentials.token

    # Call registerGcp
    url = (
        f"https://merchantapi.googleapis.com/accounts/v1/accounts/"
        f"{merchant_id}/developerRegistration:registerGcp"
    )

    resp = requests.post(
        url,
        json={"developerEmail": frappe.session.user},
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )

    if resp.status_code == 200:
        # Clear cached OAuth state
        frappe.cache.delete_value(f"gmc_oauth_state_{frappe.session.user}")
        return {
            "success": True,
            "message": "GCP project registered successfully. "
                       "It may take a few minutes to propagate. "
                       "Proceed to the next step.",
        }

    body = resp.text
    if "ALREADY_EXISTS" in body:
        frappe.cache.delete_value(f"gmc_oauth_state_{frappe.session.user}")
        return {
            "success": True,
            "message": "GCP project was already registered. Proceed to the next step.",
        }

    return {
        "success": False,
        "error": f"Registration failed (HTTP {resp.status_code}): {body}",
    }


@frappe.whitelist()
def poll_auth_status():
    """Check if the OAuth callback has stored an auth code for this user.

    Used by the web-redirect flow. The wizard polls this every 2 seconds.

    Returns dict with:
        pending (bool): True if still waiting.
        code (str): The auth code, if received.
    """
    key = f"gmc_oauth_code_{frappe.session.user}"
    code = frappe.cache.get_value(key)

    if code:
        frappe.cache.delete_value(key)
        return {"pending": False, "code": code}

    return {"pending": True}

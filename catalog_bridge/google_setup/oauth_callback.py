"""OAuth callback endpoint for the web-redirect flow."""

import frappe


@frappe.whitelist(allow_guest=True)
def handle(**kwargs):
    """Handle OAuth redirect from Google.

    Stores the auth code in Redis cache and returns a page
    telling the user to close the tab.
    """
    code = kwargs.get("code")
    state = kwargs.get("state")
    error = kwargs.get("error")

    if error:
        frappe.respond_as_web_page(
            "Authorization Failed",
            f"<p>Google returned an error: <strong>{frappe.utils.escape_html(error)}</strong></p>"
            "<p>Close this tab and try again in the setup wizard.</p>",
            indicator_color="red",
        )
        return

    if not code:
        frappe.respond_as_web_page(
            "Missing Authorization Code",
            "<p>No authorization code received. Close this tab and try again.</p>",
            indicator_color="red",
        )
        return

    if not state:
        frappe.respond_as_web_page(
            "Invalid Request",
            "<p>Missing state parameter. Close this tab and try again.</p>",
            indicator_color="red",
        )
        return

    # Look up which user initiated this flow using the state token.
    # The state→user mapping was stored in cache by get_oauth_url().
    user = frappe.cache.get_value(f"gmc_oauth_state_lookup_{state}")

    if not user:
        frappe.respond_as_web_page(
            "Session Expired",
            "<p>Could not match this callback to a setup session. "
            "The session may have expired (5-minute timeout).</p>"
            "<p>Close this tab and restart the registration step in the wizard.</p>",
            indicator_color="orange",
        )
        return

    # Store code for the wizard to pick up via poll_auth_status
    frappe.cache.set_value(
        f"gmc_oauth_code_{user}",
        code,
        expires_in_sec=300,
    )

    frappe.respond_as_web_page(
        "Authorization Successful",
        "<p>Google authorization complete. You can close this tab.</p>"
        "<p>The setup wizard will continue automatically.</p>",
        indicator_color="green",
    )

"""Register GCP project with Google Merchant Center.

One-time setup. Run:
    bench --site localhost execute catalog_bridge.register_gcp_final.run
"""
import frappe
import requests
from google_auth_oauthlib.flow import InstalledAppFlow


CLIENT_SECRETS_FILE = "/workspace/development/Temp/client_secret_951964049915-vo4c4c39lke53j8cbkfnc98npieqq0vl.apps.googleusercontent.com.json"
MERCHANT_ID = "5765040585"
DEVELOPER_EMAIL = "subscriptions@casavaventures.com"
SCOPES = ["https://www.googleapis.com/auth/content"]


def run(code=None):
    if code:
        _register_with_code(code)
        return

    # Generate the auth URL for manual flow since we can't open a browser
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES)
    flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"

    auth_url, _ = flow.authorization_url(prompt="consent")

    print()
    print("=" * 70)
    print("Open this URL in your browser and sign in with:")
    print(f"  {DEVELOPER_EMAIL}")
    print("=" * 70)
    print()
    print(auth_url)
    print()
    print("=" * 70)
    print("After authorizing, Google will show you a code.")
    print("Copy it and run:")
    print()
    print('  bench --site localhost execute catalog_bridge.register_gcp_final.run \\')
    print('    --kwargs \'{"code": "PASTE_CODE_HERE"}\'')
    print("=" * 70)


def _register_with_code(code):
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES)
    flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
    flow.fetch_token(code=code)

    access_token = flow.credentials.token
    print("Got access token.")

    # Register GCP project
    print(f"Registering GCP project with merchant {MERCHANT_ID}...")
    url = (f"https://merchantapi.googleapis.com/accounts/v1/accounts/"
           f"{MERCHANT_ID}/developerRegistration:registerGcp")

    resp = requests.post(url, json={
        "developerEmail": DEVELOPER_EMAIL,
    }, headers={
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    })

    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.text}")

    if resp.status_code == 200:
        print("\nSUCCESS! GCP project registered. Wait 5 minutes then retry sync.")
    elif "ALREADY_EXISTS" in resp.text:
        print("\nGCP project already registered. Try the sync now.")

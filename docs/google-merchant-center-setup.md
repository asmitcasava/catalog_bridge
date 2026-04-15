# Google Merchant Center Integration — Complete Setup Guide

This guide walks through every step required to connect Catalog Bridge to Google Merchant Center. It covers the **why** behind each step, not just the how.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Prerequisites](#2-prerequisites)
3. [Phase 1: Google Cloud Project Setup](#3-phase-1-google-cloud-project-setup)
4. [Phase 2: Google Merchant Center Setup](#4-phase-2-google-merchant-center-setup)
5. [Phase 3: Register GCP Project with Merchant Center](#5-phase-3-register-gcp-project-with-merchant-center)
6. [Phase 4: Create API Data Source (Feed)](#6-phase-4-create-api-data-source-feed)
7. [Phase 5: Configure Catalog Bridge in ERPNext](#7-phase-5-configure-catalog-bridge-in-erpnext)
8. [Phase 6: Initial Sync & Verification](#8-phase-6-initial-sync--verification)
9. [Troubleshooting](#9-troubleshooting)
10. [Environment-Specific Notes](#10-environment-specific-notes)
11. [Security Best Practices](#11-security-best-practices)
12. [Appendix: How the Pieces Fit Together](#12-appendix-how-the-pieces-fit-together)

---

## 1. Architecture Overview

### What is Catalog Bridge?

Catalog Bridge syncs products from ERPNext (Website Items) to external platforms. For Google Merchant Center, the data flow is:

```
ERPNext Website Item
       |
       v
  Catalog Bridge (transform)
       |
       v
  Google Merchant Products API v1
       |
       v
  Google Merchant Center Product Listing
       |
       v
  Google Shopping / Free Listings / Ads
```

### Why so many setup steps?

Google's API security model has **three independent layers**, each requiring separate configuration:

| Layer | What it does | Where you configure it |
|-------|-------------|----------------------|
| **GCP Project** | Houses your API credentials (service account) | Google Cloud Console |
| **Merchant Center** | Holds your product catalog and business info | Google Merchant Center |
| **GCP Registration** | Links your GCP project to your Merchant account | One-time API call |

Think of it like a bank: the GCP project is your ID card (proves who you are), Merchant Center is the bank account (holds your data), and GCP registration is the bank verifying your ID card is legitimate. All three must be in place before any transaction.

### Authentication Flow

```
Catalog Bridge
    |
    | reads Service Account JSON from ERPNext File Manager
    v
google.oauth2.service_account.Credentials
    |
    | signs API requests with service account private key
    v
Google Merchant Products API v1 (merchantapi.googleapis.com)
    |
    | Google checks:
    |   1. Is this service account a user on the Merchant Center account? (People & access)
    |   2. Is the GCP project registered with this Merchant account? (registerGcp)
    |   3. Is the Merchant API enabled on the GCP project? (APIs & Services)
    v
Product created/updated/deleted in Merchant Center
```

All three checks must pass. If any one fails, you get a 401/403 error.

---

## 2. Prerequisites

Before starting, ensure you have:

- [ ] A **Google Account** with admin access to your Google Merchant Center (e.g., `subscriptions@casavaventures.com`)
- [ ] A **Google Merchant Center account** (sign up at https://merchants.google.com if you don't have one)
- [ ] Access to **Google Cloud Console** (https://console.cloud.google.com) — free tier is sufficient
- [ ] **Catalog Bridge** app installed on your ERPNext/Frappe site
- [ ] Python packages installed in the bench virtualenv:
  ```bash
  /path/to/frappe-bench/env/bin/pip install \
    google-shopping-merchant-products \
    google-auth \
    google-shopping-merchant-datasources \
    google-auth-oauthlib
  ```

### Important IDs you'll collect along the way

| ID | Example | Where to find it |
|----|---------|-----------------|
| GCP Project ID | `daring-diode-493404-c6` | Cloud Console top bar |
| GCP Project Number | `951964049915` | Cloud Console > Settings |
| Merchant Center ID | `5765040585` | Merchant Center top-right corner |
| Service Account Email | `my-sa@project.iam.gserviceaccount.com` | Cloud Console > IAM > Service Accounts |
| Data Source ID | `accounts/123/dataSources/456` | Merchant Center > Data Sources |

Write these down as you go. You'll need them in later steps.

---

## 3. Phase 1: Google Cloud Project Setup

### 3.1 Create a GCP Project (skip if you have one)

1. Go to https://console.cloud.google.com
2. Click the project dropdown at the top > **New Project**
3. Name it something descriptive (e.g., `buyhomemade-merchant`)
4. Click **Create**
5. Note the **Project ID** (shown under the name, e.g., `daring-diode-493404-c6`)

> **Why a GCP project?** Google requires all API access to go through a GCP project. This is how they track quotas, billing, and permissions. Even though the Merchant API is free, the project is mandatory.

### 3.2 Enable the Merchant API

1. In Cloud Console, go to **APIs & Services** > **Library**
   (or: `https://console.cloud.google.com/apis/library?project=YOUR_PROJECT_ID`)
2. Search for **"Merchant API"**
3. Click on **"Merchant API"** (by Google)
4. Click **Enable**

> **Why?** Each API must be explicitly enabled on a project. This is Google's way of ensuring you only use APIs you intend to, and it enables quota tracking.

**Verify:** Go to **APIs & Services** > **Enabled APIs**. You should see "Merchant API" listed with status "Enabled".

### 3.3 Create a Service Account

A service account is a machine identity — it lets your server authenticate without a human signing in.

1. Go to **IAM & Admin** > **Service Accounts**
   (or: `https://console.cloud.google.com/iam-admin/serviceaccounts?project=YOUR_PROJECT_ID`)
2. Click **+ CREATE SERVICE ACCOUNT**
3. Fill in:
   - **Name:** `merchant-api-access` (or any descriptive name)
   - **ID:** auto-generated (e.g., `merchant-api-access@project.iam.gserviceaccount.com`)
   - **Description:** "Service account for Catalog Bridge to access Merchant Center API"
4. Click **Create and Continue**
5. Skip the optional roles (click **Continue**)
6. Skip granting users access (click **Done**)

> **Why a service account?** Your ERPNext server needs to make API calls 24/7 without human intervention. A service account has its own credentials (a JSON key file) that never expire and don't require browser-based login.

### 3.4 Create and Download the JSON Key

1. In the Service Accounts list, click on the service account you just created
2. Go to the **Keys** tab
3. Click **Add Key** > **Create new key**
4. Select **JSON** format
5. Click **Create**
6. The JSON file downloads automatically — **save this file securely**

> **What's in the JSON file?** It contains the service account's email, private key, project ID, and token URIs. This is the equivalent of a password — anyone with this file can act as this service account.

**SECURITY WARNING:** Never commit this file to git, share it in chat, or expose it publicly. Upload it directly to ERPNext's File Manager.

### 3.5 Create OAuth Desktop Credentials (one-time, for registration only)

This is needed only once for Phase 3 (registering the GCP project). It's separate from the service account.

1. Go to **APIs & Services** > **Credentials**
2. Click **+ CREATE CREDENTIALS** > **OAuth client ID**
3. If prompted to configure the consent screen:
   - Choose **External**
   - App name: `Catalog Bridge` (or anything)
   - User support email: your email
   - Developer contact: your email
   - Click **Save and Continue** through all steps
   - Go to **OAuth consent screen** > **Test users** > **+ ADD USERS**
   - Add: your Merchant Center admin email (e.g., `subscriptions@casavaventures.com`)
   - Save
4. Back in Credentials, click **+ CREATE CREDENTIALS** > **OAuth client ID**
5. Application type: **Desktop app**
6. Name: `Merchant Registration` (or anything)
7. Click **Create**
8. **Download the JSON** (click the download icon)

> **Why OAuth credentials too?** The GCP registration step (Phase 3) must be done by a human user, not a service account. Google enforces this as a security measure — a machine can't grant itself access. The OAuth credentials let a human authorize this one-time action.

---

## 4. Phase 2: Google Merchant Center Setup

### 4.1 Note your Merchant Center ID

1. Go to https://merchants.google.com
2. Your Merchant ID is displayed in the top-right corner next to your business name
3. It's a numeric value (e.g., `5765040585`)

### 4.2 Add the Service Account as a User

1. In Merchant Center, go to **Settings** > **Access and services**
2. Click the **People and access** tab
3. Click **Add person**
4. Enter the service account email: `your-sa@your-project.iam.gserviceaccount.com`
5. Set role: **Admin** (required for product management)
6. Click **Add**
7. The status should show **Verified** (service accounts verify instantly)

> **Why add it as a user?** Merchant Center has its own permission system independent of GCP. Even though the service account belongs to your GCP project, Merchant Center doesn't know about it until you explicitly grant access. Think of it as giving a new employee a badge — they exist in HR (GCP) but also need building access (Merchant Center).

**Verify:** The service account should appear in the People list with "Admin" role and "Verified" status.

---

## 5. Phase 3: Register GCP Project with Merchant Center

This is the step that trips everyone up. Even after:
- The Merchant API is enabled (Phase 1.2)
- The service account is a Merchant Center user (Phase 2.2)

...you STILL get `GCP_NOT_REGISTERED` errors. Why?

> **Why registration?** Google maintains a separate registry of which GCP projects are allowed to call the Merchant API for each Merchant account. This is a security boundary — it prevents someone who compromises a service account from accessing arbitrary Merchant accounts. The registration says: "I, the human admin, authorize GCP project X to access Merchant account Y."

### 5.1 Prepare the Registration Script

Catalog Bridge includes a registration helper. Configure it with your details:

**File:** `apps/catalog_bridge/catalog_bridge/register_gcp_final.py`

Update these constants:
```python
CLIENT_SECRETS_FILE = "/path/to/your/client_secret_xxx.json"  # OAuth Desktop JSON from Phase 1.5
MERCHANT_ID = "5765040585"                                     # From Phase 2.1
DEVELOPER_EMAIL = "your-admin@example.com"                     # Your Merchant Center admin email
```

### 5.2 Generate the Authorization URL

```bash
bench --site YOUR_SITE execute catalog_bridge.register_gcp_final.run
```

This prints a URL. Open it in your browser.

### 5.3 Authorize in Browser

1. Open the printed URL in your browser
2. Sign in with your **Merchant Center admin** Google account
3. If you see "This app isn't verified" or "Catalog Bridge has not completed verification":
   - This is expected for test/internal apps
   - Click **Advanced** > **Go to Catalog Bridge (unsafe)**
   - This is safe — it's YOUR app in YOUR GCP project
4. Grant the requested permissions (Merchant Center access)
5. Google will display an **authorization code** — copy it

> **Why the "unverified app" warning?** Google verification is for apps used by the general public. Internal/test apps don't need it. The warning is just Google being cautious. Since you own both the GCP project and the Merchant account, it's perfectly safe to proceed.

### 5.4 Complete Registration

```bash
bench --site YOUR_SITE execute catalog_bridge.register_gcp_final.run \
  --kwargs '{"code": "PASTE_THE_CODE_HERE"}'
```

Expected output:
```
Got access token.
Registering GCP project with merchant 5765040585...
Status: 200
Response: {
  "name": "accounts/5765040585/developerRegistration",
  "gcpIds": ["951964049915"]
}

SUCCESS! GCP project registered. Wait 5 minutes then retry sync.
```

### 5.5 Wait 5 Minutes

Google requires a propagation delay after registration. This is not optional — API calls made within 5 minutes of registration will still return `GCP_NOT_REGISTERED`.

> **This is a one-time step.** Once registered, the GCP project stays registered permanently. You never need to do this again unless you create a new GCP project or a new Merchant Center account.

---

## 6. Phase 4: Create API Data Source (Feed)

Google Merchant Center requires a "data source" (formerly called "feed") that tells it where product data comes from.

### 6.1 Create an API Data Source

1. In Merchant Center, go to **Products & store** > **Data sources** (in the left sidebar under Settings)
2. Click **Add data source** (or **+**)
3. Choose **API** as the source type
4. Set:
   - **Name:** `API Feed` (or any name)
   - **Country:** Your target country (e.g., India)
   - **Language:** Your content language (e.g., English)
5. Save

### 6.2 Note the Data Source ID

After creation, the data source will have an ID in the format:
```
accounts/5765040585/dataSources/10635750514
```

You can find this in the URL when viewing the data source, or Catalog Bridge can auto-detect it.

> **Why a data source?** Merchant Center can receive products from multiple sources — CSV files, Google Sheets, APIs, automated feeds, etc. The data source tells Merchant Center which products came from which source, so it can track updates and handle conflicts.

### 6.3 Auto-Detection (Alternative)

If you leave the Data Source field blank in Catalog Platform, Catalog Bridge will automatically find the first API-type data source and cache its ID. This works well if you have only one API feed.

---

## 7. Phase 5: Configure Catalog Bridge in ERPNext

### 7.1 Upload the Service Account JSON

1. In ERPNext, go to **File Manager** (or the file will be uploaded automatically when you attach it)
2. The JSON key file from Phase 1.4 will be attached to the Catalog Platform doc

### 7.2 Create a Catalog Platform Document

1. Go to: `/app/catalog-platform/new`
2. Fill in:

| Field | Value | Notes |
|-------|-------|-------|
| **Platform Name** | `Google Merchant Center` | Free text, used as the doc name |
| **Platform Type** | `Google Merchant Center` | Select from dropdown |
| **Enabled** | ✓ | Check to activate syncing |
| **Price List** | `Standard Selling` | The ERPNext Price List to pull prices from |
| **Service Account JSON** | (attach file) | Upload the JSON key from Phase 1.4 |
| **Merchant ID** | `5765040585` | Numeric ID from Phase 2.1 |
| **Content Language** | `en` | ISO 639-1 code (en, hi, fr, etc.) |
| **Feed Label** | `IN` | Target country code (IN, US, GB, etc.) |
| **Data Source** | (leave blank) | Auto-detected, or paste full path like `accounts/123/dataSources/456` |
| **Frontend URL** | `https://buyhomemade.com` | Your customer-facing website |
| **Product URL Template** | `{{ frontend_url }}/{{ route }}` | Jinja template for product links |
| **Image URL Template** | `{{ frontend_url }}{{ website_image }}` | Jinja template for image URLs |
| **Sync on Save** | ✓ | Auto-sync when a Website Item is saved |

3. Save

### 7.3 Field Reference

**Content Language** — The language of your product data. Must match the language your products are written in. Google uses this for search matching.

**Feed Label** — Controls which country/region your products target. Common values:
- `IN` — India
- `US` — United States
- `GB` — United Kingdom
- `online` — Generic (not recommended for production)

**Product URL Template** — Jinja template that generates the product page URL. Available variables:
- `{{ frontend_url }}` — Your Frontend URL setting
- `{{ route }}` — The Website Item's route (slug)
- `{{ item_code }}` — ERPNext Item Code
- `{{ item_name }}` — Item Name
- `{{ name }}` — Website Item document name
- `{{ web_item_name }}` — Web Item Name

**Image URL Template** — Jinja template for product images. Only used when the image path is relative (starts with `/files/`). Absolute URLs (starting with `http`) pass through unchanged. Available variables:
- `{{ frontend_url }}` — Your Frontend URL setting
- `{{ website_image }}` — The image path (e.g., `/files/product.jpg`)
- `{{ item_code }}` — ERPNext Item Code

---

## 8. Phase 6: Initial Sync & Verification

### 8.1 Run Initial Sync

Sync all published Website Items to Google Merchant Center:

```bash
bench --site YOUR_SITE execute catalog_bridge.tasks.initial_sync \
  --kwargs '{"platform_name": "Google Merchant Center"}'
```

Or click the **"Sync All Items"** button on the Catalog Platform form.

### 8.2 Verify in Merchant Center

1. Go to **Merchant Center** > **Products & store** > **Products**
2. Products should appear within a few minutes
3. Check for any disapproved products and fix the issues

### 8.3 Monitor Sync Logs

In ERPNext, go to **Catalog Sync Log** list view (`/app/catalog-sync-log`) to see:
- Individual product sync status (Success / Failed / Retrying)
- Error messages for failed syncs
- Request and response data for debugging

### 8.4 Check Error Logs

Go to **Error Log** (`/app/error-log`) and filter by title containing "Catalog Bridge" for detailed tracebacks.

---

## 9. Troubleshooting

### Error: `GCP_NOT_REGISTERED`

```
GCP project with id xxx is not registered with the merchant account.
```

**Cause:** Phase 3 (GCP Registration) was not completed.

**Fix:** Run the registration script as described in Phase 3. This is a one-time API call that links your GCP project to your Merchant account.

**Common mistakes:**
- Confusing "adding service account as user" (Phase 2.2) with "registering the GCP project" (Phase 3) — these are different steps
- Using OAuth Playground for registration — Google blocks shared GCP projects. You must use your own OAuth credentials
- Using a service account for registration — only human users can register GCP projects

---

### Error: `No module named 'google.shopping'`

**Cause:** Google packages not installed in the bench virtualenv.

**Fix:**
```bash
/path/to/frappe-bench/env/bin/pip install \
  google-shopping-merchant-products \
  google-auth \
  google-shopping-merchant-datasources
```

Note: Install with the **bench virtualenv pip**, not the system pip. After installing, restart workers:
```bash
cd /path/to/frappe-bench && bench restart
```

---

### Error: `Unknown field for ProductInput: channel`

**Cause:** Stale `.pyc` bytecode cache.

**Fix:**
```bash
find /path/to/frappe-bench/apps/catalog_bridge -name "*.pyc" -delete
find /path/to/frappe-bench/apps/catalog_bridge -name "__pycache__" -type d -exec rm -rf {} +
cd /path/to/frappe-bench && bench restart
```

---

### Error: `'new'` or `'in_stock'`

**Cause:** Google Merchant API v1 uses uppercase enum values.

**Fix:** Ensure the connector uses:
- Condition: `NEW`, `USED`, `REFURBISHED` (not `new`, `used`)
- Availability: `IN_STOCK`, `OUT_OF_STOCK`, `PREORDER` (not `in_stock`, `out_of_stock`)

---

### Error: `unauthorized` / `PERMISSION_DENIED`

**Check all three layers:**

1. **Merchant API enabled?** — Cloud Console > APIs & Services > Enabled APIs
2. **Service account is Merchant Center user?** — Merchant Center > Settings > Access and services > People
3. **GCP project registered?** — Run the registration script (Phase 3)

---

### Error: `This app isn't verified`

**Cause:** Your OAuth client (used only for registration) hasn't gone through Google's app verification.

**Fix:** This is expected and safe for internal use. Click **Advanced** > **Go to [App Name] (unsafe)**. Since you own the GCP project and the app only accesses your own Merchant account, this is fine.

Alternatively, add yourself as a test user: Cloud Console > APIs & Services > OAuth consent screen > Test users > Add your email.

---

### Products show "Disapproved" in Merchant Center

Common reasons:
- **Missing required fields:** title, description, link, image_link, price, availability
- **Image URL not accessible:** Ensure your frontend URL is publicly reachable and images load
- **Product URL returns 404:** Check your Product URL Template renders correct URLs
- **Price mismatch:** Price on landing page must match price in feed
- **Missing shipping info:** Configure shipping in Merchant Center settings

---

## 10. Environment-Specific Notes

### Development / Local

- Use a **test Merchant Center account** — don't sync test products to production
- You can use the same GCP project across environments, but use different Merchant accounts
- Set `Sync on Save` to unchecked to prevent accidental syncs during development
- The service account JSON can be stored locally — just reference the file path

### Staging / QA

- Create a separate Catalog Platform doc pointing to a test Merchant account
- Run initial sync and verify products appear correctly before promoting to production
- Test these scenarios:
  - [ ] New product published → appears in Merchant Center
  - [ ] Price changed → updates in Merchant Center
  - [ ] Stock goes to 0 → shows "OUT_OF_STOCK" in Merchant Center
  - [ ] Stock replenished → shows "IN_STOCK" in Merchant Center
  - [ ] Product unpublished → deleted from Merchant Center
  - [ ] Bulk sync (initial_sync) → all products appear
  - [ ] Failed sync → retried automatically (check Catalog Sync Log)
  - [ ] 3 consecutive failures → alert email sent
  - [ ] Daily reconciliation → missing products re-synced

### Production

- Use a dedicated service account per environment
- Set up the **Alert Email** field on the Catalog Platform for failure notifications
- Monitor the **Catalog Sync Log** for persistent failures
- The daily reconciliation job automatically catches and fixes drift
- Consider setting `Sync Frequency` to "Every 5 minutes" for near-real-time sync without overloading on-save hooks

---

## 11. Security Best Practices

### Service Account JSON Key

- **Never commit to git.** Add `*.json` key files to `.gitignore`
- **Upload directly to ERPNext** via the Catalog Platform form's Attach field
- **Restrict access** to the Catalog Platform doctype to System Managers only (default)
- **Rotate keys periodically:** Delete old keys and create new ones in Cloud Console > Service Accounts > Keys

### OAuth Credentials (Desktop Client)

- Only needed once for GCP registration (Phase 3)
- Can be deleted from Cloud Console after registration is complete
- The `register_gcp_final.py` script and `client_secret_*.json` can be removed after setup

### Principle of Least Privilege

- The service account only needs **Admin** role in Merchant Center (for product CRUD)
- No GCP IAM roles are needed on the service account itself — it only calls Merchant API, not GCP services
- Don't reuse this service account for other purposes

---

## 12. Appendix: How the Pieces Fit Together

### Complete Dependency Graph

```
Google Cloud Console                    Google Merchant Center
========================               ========================
                                       
1. Create GCP Project ──────────────>  2. Note Merchant ID
   (Project ID, Project Number)           (numeric, e.g. 5765040585)
                                       
3. Enable Merchant API                4. Add service account as
   (APIs & Services > Library)            Admin user
   (merchantapi.googleapis.com)           (Settings > Access & services)
                                       
5. Create Service Account             6. Create API Data Source
   (IAM > Service Accounts)              (Products > Data Sources)
   Download JSON key                      Note the data source ID
                                       
7. Create OAuth Desktop Client         
   (APIs & Services > Credentials)     
   Add test user to consent screen     
                                       
          ┌─── 8. Register GCP Project ───┐
          │    (one-time API call using     │
          │     OAuth token from step 7)   │
          └────────────────────────────────┘
                                       
                    ERPNext
          ========================
                                       
          9. Upload service account JSON
          10. Create Catalog Platform doc
              (Merchant ID, Price List,
               Feed Label, Language, etc.)
          11. Run initial sync
          12. Verify in Merchant Center
```

### What Each Google API Package Does

| Package | PyPI Name | Purpose |
|---------|-----------|---------|
| `google-auth` | `google-auth` | Handles service account authentication, token signing |
| `google-shopping-merchant-products` | `google-shopping-merchant-products` | Product CRUD (insert, delete, list, get) |
| `google-shopping-merchant-datasources` | `google-shopping-merchant-datasources` | List/detect API data sources |
| `google-auth-oauthlib` | `google-auth-oauthlib` | OAuth2 flow for human user auth (registration only) |

### Google Merchant API v1 Key Concepts

**ProductInput vs Product:**
- `ProductInput` is what you **send** to Google (your data)
- `Product` is what Google **returns** (your data + Google's processing results)
- You insert `ProductInput`, you read `Product`

**Price in Micros:**
- Google uses "micros" for prices: 1 currency unit = 1,000,000 micros
- Example: ₹150.00 = 150,000,000 micros
- This avoids floating-point precision issues

**Enum Values (uppercase):**
- Condition: `NEW`, `USED`, `REFURBISHED`
- Availability: `IN_STOCK`, `OUT_OF_STOCK`, `PREORDER`, `BACKORDER`
- These are proto enum values and must be uppercase

**Product ID Format:**
- `online~{language}~{feed_label}~{offer_id}`
- Example: `online~en~IN~BHM-ITM-10001`
- This is how Google uniquely identifies products across channels and locales

**Data Source:**
- Full format: `accounts/{merchant_id}/dataSources/{data_source_id}`
- If you enter just the numeric ID (e.g., `10635750514`), Catalog Bridge auto-expands it

---

## Quick Reference Card

```
Setup Checklist (do these in order):
=====================================

GCP Console (console.cloud.google.com):
  [ ] Create project (or use existing)
  [ ] Enable Merchant API
  [ ] Create service account
  [ ] Download JSON key
  [ ] Create OAuth Desktop client (one-time)
  [ ] Add yourself as test user on consent screen

Merchant Center (merchants.google.com):
  [ ] Note your Merchant ID
  [ ] Add service account email as Admin user
  [ ] Create API data source (feed)

Registration (one-time CLI command):
  [ ] Run register_gcp_final.py — get auth URL
  [ ] Authorize in browser with admin account
  [ ] Run register_gcp_final.py with code
  [ ] Wait 5 minutes

ERPNext:
  [ ] Upload service account JSON
  [ ] Create Catalog Platform doc
  [ ] Set Merchant ID, Price List, Feed Label
  [ ] Run initial sync
  [ ] Verify products in Merchant Center
```

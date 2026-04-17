# TODOS

## Extract shared connector methods to base class

**What:** Move `_build_product_url`, `_build_image_url`, `_get_price`, `_get_availability`, and `_apply_field_overrides` from `MetaCatalogConnector` and `GoogleMerchantConnector` into the `CatalogConnector` base class. Add a `price_multiplier` property (100 for Meta cents, 1_000_000 for Google micros) to handle the one difference.

**Why:** ~80 lines of near-identical code duplicated across both connectors. Will compound if a third connector is added (e.g., Amazon, Shopify).

**Pros:** DRY, single place to fix URL/price/availability bugs, easier to add new connectors.

**Cons:** Minor refactor risk (both connectors must be re-tested after extraction).

**Context:** Both connectors were built independently. The duplication is obvious in hindsight. The only meaningful difference is price representation (cents vs micros) and availability strings (lowercase for Meta, uppercase for Google).

**Depends on:** Nothing. Pure refactor. Should not be bundled with the wizard PR.

**Files:** `catalog_bridge/connectors/base.py`, `catalog_bridge/connectors/meta_catalog.py`, `catalog_bridge/connectors/google_merchant.py`

---

## Verify data source creation timestamp for sorting

**What:** Check whether the Google Datasources API response includes a creation timestamp field on `DataSource` objects. If yes, sort by it in the wizard's Step 5 dropdown to pre-select the most recently created `PRIMARY_PRODUCT_DATA_SOURCE`. If not, fall back to display_name ordering.

**Why:** Users with multiple data sources (e.g., separate feeds for different countries) need the wizard to pre-select the right one. Most recently created is the best heuristic.

**Pros:** Better UX for multi-feed accounts.

**Cons:** Minimal. If the field doesn't exist, display_name ordering is fine.

**Context:** Flagged in design doc reviewer concern #2. The `google-shopping-merchant-datasources` SDK is new with thin documentation. Needs hands-on verification during implementation.

**Depends on:** Wizard backend implementation (Step 5 / `detect_data_sources`).

**Files:** `catalog_bridge/google_setup/data_source.py`

---

## Create DESIGN.md for Catalog Bridge

**What:** Document the app's design conventions: Frappe component usage, color variables, spacing patterns, UX principles for setup flows. Seed with the wizard's design decisions (CSS stepper, loading states, error display pattern, empty state warmth).

**Why:** Without it, every new feature invents its own visual language. The wizard establishes patterns (step indicator, progressive disclosure, branded callback page) that should be reused.

**Pros:** Consistency across future features, faster design reviews, onboarding for contributors.

**Cons:** Maintenance overhead for a small app. May be premature before a second major UI feature.

**Context:** Flagged during plan-design-review. The wizard is the first significant UI in this app. Its patterns should be captured before they're forgotten.

**Depends on:** Wizard PR should ship first (the wizard IS the design system seed).

**Files:** `DESIGN.md` (new file at app root)

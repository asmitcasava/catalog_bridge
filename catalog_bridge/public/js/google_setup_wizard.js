/**
 * Google Merchant Center Setup Wizard
 *
 * A 5-step guided flow that reduces Google Merchant setup from 12 manual steps
 * to a single wizard inside ERPNext.
 *
 * Steps:
 *   1. Prerequisites check (Python packages)
 *   2. Service account JSON upload + Merchant ID
 *   3. Test Merchant Center access
 *   4. GCP project registration (OAuth)
 *   5. Data source detection + feed config
 */

window.catalog_bridge = window.catalog_bridge || {};

catalog_bridge.GoogleSetupWizard = class GoogleSetupWizard {
	constructor(frm) {
		this.frm = frm;
		this.current_step = 1;
		this.total_steps = 5;
		this.state = {};
		this.poll_timer = null;
		this.show();
	}

	show() {
		this.dialog = new frappe.ui.Dialog({
			title: __("Setup Google Merchant Center"),
			size: "large",
			minimizable: false,
			static: true,
			primary_action_label: __("Next"),
			primary_action: () => this.next_step(),
			secondary_action_label: __("Back"),
			secondary_action: () => this.prev_step(),
		});

		this.dialog.$wrapper.find(".modal-dialog").css("max-width", "720px");

		// Build step containers
		this.dialog.fields_area = this.dialog.$body;
		this.dialog.$body.html("");
		this.$steps = $('<div class="wizard-steps"></div>').appendTo(this.dialog.$body);

		for (let i = 1; i <= this.total_steps; i++) {
			this.$steps.append(`<div class="wizard-step" data-step="${i}" style="display:none; padding: 15px;"></div>`);
		}

		// Add stepper indicator
		this._render_stepper();

		this.dialog.show();

		// Determine starting step based on existing config
		this._determine_start_step();
	}

	_render_stepper() {
		const labels = [
			"Prerequisites",
			"Service Account",
			"Test Access",
			"Registration",
			"Data Source",
		];

		let html = '<div class="wizard-stepper" style="display:flex; justify-content:space-between; padding:15px 15px 0; border-bottom:1px solid var(--border-color); margin-bottom:5px;">';
		for (let i = 1; i <= this.total_steps; i++) {
			html += `
				<div class="step-indicator" data-step="${i}" style="text-align:center; flex:1; padding-bottom:12px; cursor:default;">
					<div class="step-number" style="width:28px; height:28px; border-radius:50%; display:inline-flex; align-items:center; justify-content:center; font-size:13px; font-weight:600; margin-bottom:4px;
						background: var(--bg-color); border: 1.5px solid var(--border-color); color: var(--text-muted);">
						${i}
					</div>
					<div style="font-size:11px; color:var(--text-muted);">${labels[i - 1]}</div>
				</div>`;
		}
		html += "</div>";
		this.$steps.before(html);
	}

	_update_stepper() {
		this.dialog.$wrapper.find(".step-indicator").each((_, el) => {
			const $el = $(el);
			const step = parseInt($el.data("step"));
			const $num = $el.find(".step-number");

			if (step < this.current_step) {
				$num.css({ background: "var(--primary)", border: "1.5px solid var(--primary)", color: "#fff" });
				$num.html("&#10003;");
			} else if (step === this.current_step) {
				$num.css({ background: "var(--primary)", border: "1.5px solid var(--primary)", color: "#fff" });
				$num.text(step);
			} else {
				$num.css({ background: "var(--bg-color)", border: "1.5px solid var(--border-color)", color: "var(--text-muted)" });
				$num.text(step);
			}
		});
	}

	_determine_start_step() {
		const doc = this.frm.doc;

		if (!doc.google_service_account_json) {
			this._go_to_step(1);
		} else if (!doc.google_merchant_id) {
			this._go_to_step(2);
		} else if (!doc.google_data_source) {
			// Need to test access to determine if step 3 or 4
			this._go_to_step(3);
		} else {
			// All configured — show completion
			this._go_to_step(5);
		}
	}

	_go_to_step(step) {
		this.current_step = step;
		this.$steps.find(".wizard-step").hide();
		this.$steps.find(`.wizard-step[data-step="${step}"]`).show();
		this._update_stepper();
		this._update_buttons();

		// Render step content
		const render_fn = `_render_step_${step}`;
		if (this[render_fn]) {
			this[render_fn]();
		}
	}

	_update_buttons() {
		const $primary = this.dialog.get_primary_btn();
		const $secondary = this.dialog.$wrapper.find(".btn-modal-secondary");

		// Back button
		if (this.current_step <= 1) {
			$secondary.hide();
		} else {
			$secondary.show();
		}

		// Next button
		if (this.current_step >= this.total_steps) {
			$primary.text(__("Finish"));
		} else {
			$primary.text(__("Next"));
		}

		// Disable next by default — each step enables it after validation
		$primary.prop("disabled", true);
	}

	_enable_next() {
		this.dialog.get_primary_btn().prop("disabled", false);
	}

	_disable_next() {
		this.dialog.get_primary_btn().prop("disabled", true);
	}

	next_step() {
		if (this.current_step >= this.total_steps) {
			this._finish();
			return;
		}

		// Run step-specific save logic before advancing
		const save_fn = `_save_step_${this.current_step}`;
		if (this[save_fn]) {
			const result = this[save_fn]();
			if (result === false) return;
		}

		this._go_to_step(this.current_step + 1);
	}

	prev_step() {
		if (this.current_step > 1) {
			this._go_to_step(this.current_step - 1);
		}
	}

	_finish() {
		this._cleanup_poll();
		this.dialog.hide();
		this.frm.reload_doc();
		frappe.show_alert({ message: __("Google Merchant Center setup complete!"), indicator: "green" });
	}

	_cleanup_poll() {
		if (this.poll_timer) {
			clearInterval(this.poll_timer);
			this.poll_timer = null;
		}
	}

	// ─── Step 1: Prerequisites ──────────────────────────────────────

	_render_step_1() {
		const $step = this.$steps.find('.wizard-step[data-step="1"]');
		$step.html(`
			<h5 style="margin-bottom:12px;">${__("Prerequisites Check")}</h5>
			<p class="text-muted">${__("Checking if required Python packages are installed...")}</p>
			<div class="prereq-results" style="margin-top:15px;"></div>
		`);

		frappe.xcall("catalog_bridge.google_setup.prerequisites.check_prerequisites").then((r) => {
			let html = "";

			for (const pkg of r.packages) {
				const icon = pkg.installed
					? '<span style="color:var(--green-500);">&#10003;</span>'
					: '<span style="color:var(--red-500);">&#10007;</span>';
				html += `<div style="padding:6px 0;">${icon} <code>${pkg.package}</code></div>`;
			}

			if (!r.all_installed) {
				html += `
					<div class="frappe-control" style="margin-top:15px;">
						<div class="alert alert-warning" role="alert">
							<strong>${__("Missing packages.")}</strong> ${__("Run this command on your server:")}
							<div style="margin-top:8px; position:relative;">
								<pre style="background: var(--bg-color); padding: 10px; border-radius: 4px; margin:0; cursor:pointer;"
									 onclick="frappe.utils.copy_to_clipboard(this.textContent)"
									 title="${__("Click to copy")}">${r.install_command}</pre>
							</div>
							<p class="text-muted" style="margin-top:8px; margin-bottom:0; font-size:12px;">
								${__("After installing, restart the bench and re-open this wizard.")}
							</p>
						</div>
					</div>`;
			} else {
				html += `
					<div class="alert alert-success" style="margin-top:15px;" role="alert">
						${__("All required packages are installed.")}
					</div>`;
				this._enable_next();
			}

			$step.find(".prereq-results").html(html);
		});
	}

	// ─── Step 2: Service Account + Merchant ID ──────────────────────

	_render_step_2() {
		const $step = this.$steps.find('.wizard-step[data-step="2"]');
		const existing_json = this.frm.doc.google_service_account_json;
		const existing_mid = this.frm.doc.google_merchant_id;

		$step.html(`
			<h5 style="margin-bottom:4px;">${__("GCP Project & Service Account")}</h5>
			<p class="text-muted" style="margin-bottom:15px;">${__("Upload your service account JSON key and enter your Merchant Center ID.")}</p>

			<div class="step2-instructions" style="margin-bottom:15px;">
				<details>
					<summary style="cursor:pointer; font-weight:500; color:var(--primary);">${__("How to get these")}</summary>
					<ol style="margin-top:8px; padding-left:20px; line-height:2;">
						<li>${__("Go to")} <a href="https://console.cloud.google.com/projectcreate" target="_blank">Google Cloud Console</a> ${__("and create a project (or select an existing one)")}</li>
						<li>${__("Enable the")} <strong>Merchant API</strong>: ${__("search for 'Merchant API' in the API Library and enable it")}</li>
						<li>${__("Go to")} <strong>IAM & Admin &gt; Service Accounts</strong> ${__("and create a service account")}</li>
						<li>${__("Create a JSON key: click the service account &gt; Keys &gt; Add Key &gt; JSON")}</li>
						<li>${__("Find your Merchant ID in")} <a href="https://merchants.google.com/" target="_blank">Merchant Center</a> ${__("(top-right corner)")}</li>
					</ol>
				</details>
			</div>

			<div class="sa-upload-area" style="margin-bottom:15px;">
				<label class="control-label">${__("Service Account JSON Key")}</label>
				<div class="sa-file-status" style="margin-top:5px;"></div>
				<button class="btn btn-sm btn-default sa-upload-btn" style="margin-top:8px;">
					${existing_json ? __("Re-upload JSON Key") : __("Upload JSON Key")}
				</button>
			</div>

			<div class="sa-validation-result"></div>

			<div class="merchant-id-area" style="margin-top:15px;">
				<label class="control-label" style="display:block;">${__("Merchant Center ID")}</label>
				<p class="text-muted" style="font-size:12px; margin-bottom:5px;">${__("Numeric ID from Merchant Center dashboard (top-right).")}</p>
				<input type="text" class="form-control merchant-id-input"
					   placeholder="e.g. 1234567890" value="${existing_mid || ""}"
					   style="max-width:300px;">
			</div>
		`);

		// Show existing file status
		if (existing_json) {
			this._show_sa_status($step, existing_json);
		}

		// Upload button
		$step.find(".sa-upload-btn").on("click", () => this._upload_sa_json($step));

		// Merchant ID input — validate on change
		$step.find(".merchant-id-input").on("input", () => this._check_step2_complete($step));

		// Check if already complete
		this._check_step2_complete($step);
	}

	_show_sa_status($step, file_url) {
		const filename = file_url.split("/").pop();
		$step.find(".sa-file-status").html(`
			<span style="color:var(--green-500);">&#10003;</span>
			<code>${filename}</code>
		`);

		// Validate the JSON
		frappe.xcall("catalog_bridge.google_setup.validate.validate_service_account", {
			json_file_url: file_url,
		}).then((r) => {
			if (r.valid) {
				this.state.project_id = r.project_id;
				this.state.client_email = r.client_email;
				$step.find(".sa-validation-result").html(`
					<div class="alert alert-success" style="padding:10px; margin-top:8px;" role="alert">
						<strong>${__("Valid service account")}</strong><br>
						${__("Project")}: <code>${r.project_id}</code><br>
						${__("Email")}: <code>${r.client_email}</code>
					</div>
				`);
				this._check_step2_complete($step);
			} else {
				$step.find(".sa-validation-result").html(`
					<div class="alert alert-danger" style="padding:10px; margin-top:8px;" role="alert">
						${r.error}
					</div>
				`);
			}
		});
	}

	_upload_sa_json($step) {
		new frappe.ui.FileUploader({
			doctype: this.frm.doctype,
			docname: this.frm.docname,
			folder: "Home",
			restrictions: { allowed_file_types: [".json"] },
			make_attachments_public: false,
			on_success: (file) => {
				const file_url = file.file_url;
				this.frm.set_value("google_service_account_json", file_url);
				this.frm.dirty();
				this._show_sa_status($step, file_url);
			},
		});
	}

	_check_step2_complete($step) {
		const has_json = this.frm.doc.google_service_account_json && this.state.project_id;
		const merchant_id = $step.find(".merchant-id-input").val().trim();
		const has_mid = /^\d+$/.test(merchant_id);

		if (has_json && has_mid) {
			this.state.merchant_id = merchant_id;
			this._enable_next();
		} else {
			this._disable_next();
		}
	}

	_save_step_2() {
		const mid = this.state.merchant_id;
		if (mid && mid !== this.frm.doc.google_merchant_id) {
			this.frm.set_value("google_merchant_id", mid);
			this.frm.dirty();
		}
		// Save the doc so subsequent API calls can read the updated fields
		this.frm.save();
	}

	// ─── Step 3: Test Merchant Access ───────────────────────────────

	_render_step_3() {
		const $step = this.$steps.find('.wizard-step[data-step="3"]');
		const sa_email = this.state.client_email || "your-service-account@project.iam.gserviceaccount.com";

		$step.html(`
			<h5 style="margin-bottom:4px;">${__("Test Merchant Center Access")}</h5>
			<p class="text-muted" style="margin-bottom:15px;">
				${__("Before testing, make sure the service account has access to your Merchant Center.")}
			</p>

			<div class="sa-instructions" style="margin-bottom:15px;">
				<details open>
					<summary style="cursor:pointer; font-weight:500; color:var(--primary);">${__("How to grant access")}</summary>
					<ol style="margin-top:8px; padding-left:20px; line-height:2;">
						<li>${__("Go to")} <a href="https://merchants.google.com/mc/settings/access" target="_blank">Merchant Center &gt; Settings &gt; Access</a></li>
						<li>${__("Click")} <strong>${__("Add user")}</strong></li>
						<li>${__("Enter this email:")} <code style="user-select:all; cursor:pointer;" title="${__("Click to select")}">${sa_email}</code></li>
						<li>${__("Set role to")} <strong>Admin</strong></li>
						<li>${__("Save and come back here")}</li>
					</ol>
				</details>
			</div>

			<div class="test-access-area" style="text-align:center; padding:15px 0;">
				<button class="btn btn-primary btn-md test-access-btn">${__("Test Connection")}</button>
			</div>

			<div class="test-result"></div>
		`);

		$step.find(".test-access-btn").on("click", () => this._test_access($step));
	}

	_test_access($step) {
		const $btn = $step.find(".test-access-btn");
		const $result = $step.find(".test-result");

		$btn.prop("disabled", true).text(__("Testing..."));
		$result.html("");

		frappe.xcall("catalog_bridge.google_setup.validate.test_merchant_access", {
			platform_name: this.frm.doc.name,
		}).then((r) => {
			$btn.prop("disabled", false).text(__("Test Connection"));

			if (r.status === "success") {
				this.state.access_ok = true;
				this.state.data_sources = r.data_sources;
				$result.html(`
					<div class="alert alert-success" role="alert">
						<strong>${__("Connection successful!")}</strong>
						${__("Found")} ${r.data_sources.length} ${__("data source(s).")}
						${__("Click Next to continue.")}
					</div>
				`);
				this._enable_next();
				// Skip step 4 (registration) — mark it in state
				this.state.skip_registration = true;
			} else if (r.status === "gcp_not_registered") {
				this.state.access_ok = false;
				this.state.skip_registration = false;
				$result.html(`
					<div class="alert alert-warning" role="alert">
						<strong>${__("GCP project not registered.")}</strong>
						${r.error}<br>
						${__("Click Next to complete the one-time registration.")}
					</div>
				`);
				this._enable_next();
			} else if (r.status === "permission_denied") {
				$result.html(`
					<div class="alert alert-danger" role="alert">
						<strong>${__("Permission denied.")}</strong> ${r.error}
					</div>
				`);
			} else {
				$result.html(`
					<div class="alert alert-danger" role="alert">
						<strong>${__("Error:")}</strong> ${r.error}
						<details style="margin-top:8px;">
							<summary style="cursor:pointer; font-size:12px;">${__("Technical details")}</summary>
							<pre style="margin-top:5px; font-size:11px; white-space:pre-wrap;">${frappe.utils.escape_html(r.error)}</pre>
						</details>
					</div>
				`);
			}
		}).catch((err) => {
			$btn.prop("disabled", false).text(__("Test Connection"));
			$result.html(`
				<div class="alert alert-danger" role="alert">${err.message || err}</div>
			`);
		});
	}

	_save_step_3() {
		// If registration can be skipped, jump to step 5
		if (this.state.skip_registration) {
			// Override next_step to go to 5 instead of 4
			this.current_step = 4; // next_step will increment to 5
		}
	}

	// ─── Step 4: GCP Registration (OAuth) ───────────────────────────

	_render_step_4() {
		const $step = this.$steps.find('.wizard-step[data-step="4"]');
		const project_id = this.state.project_id || "your-project-id";

		$step.html(`
			<h5 style="margin-bottom:4px;">${__("GCP Project Registration")}</h5>
			<p class="text-muted" style="margin-bottom:15px;">
				${__("Your GCP project needs a one-time registration with Merchant Center. This requires your personal Google login.")}
			</p>

			<details open>
				<summary style="cursor:pointer; font-weight:500; color:var(--primary);">${__("Step-by-step instructions")}</summary>
				<ol style="margin-top:8px; padding-left:20px; line-height:2;">
					<li>${__('Go to')} <a href="https://console.cloud.google.com/apis/credentials?project=${project_id}" target="_blank">${__("GCP Credentials page")}</a></li>
					<li>${__('Click')} <strong>${__("Create Credentials")}</strong> &gt; <strong>${__("OAuth client ID")}</strong></li>
					<li>${__("If prompted, configure the consent screen (External, add your email as test user)")}</li>
					<li>${__('Application type:')} <strong>${__("Desktop app")}</strong></li>
					<li>${__("Copy the Client ID and Client Secret below")}</li>
				</ol>
			</details>

			<div style="margin-top:15px;">
				<div style="margin-bottom:10px;">
					<label class="control-label">${__("OAuth Client ID")}</label>
					<input type="text" class="form-control oauth-client-id" placeholder="xxxx.apps.googleusercontent.com">
				</div>
				<div style="margin-bottom:10px;">
					<label class="control-label">${__("OAuth Client Secret")}</label>
					<input type="password" class="form-control oauth-client-secret" placeholder="GOCSPX-...">
				</div>
			</div>

			<div class="oauth-flow-area" style="text-align:center; padding:10px 0;">
				<button class="btn btn-primary btn-md start-oauth-btn" disabled>
					${__("Authorize with Google")}
				</button>
			</div>

			<div class="oauth-code-area" style="display:none; margin-top:15px;">
				<label class="control-label">${__("Authorization Code")}</label>
				<p class="text-muted" style="font-size:12px;">${__("After authorizing in Google, paste the code shown here:")}</p>
				<input type="text" class="form-control oauth-auth-code" placeholder="${__("Paste authorization code here")}">
				<button class="btn btn-primary btn-sm complete-reg-btn" style="margin-top:10px;" disabled>
					${__("Complete Registration")}
				</button>
			</div>

			<div class="oauth-result" style="margin-top:15px;"></div>
		`);

		// Enable authorize button when both fields filled
		$step.find(".oauth-client-id, .oauth-client-secret").on("input", () => {
			const has_id = $step.find(".oauth-client-id").val().trim().length > 0;
			const has_secret = $step.find(".oauth-client-secret").val().trim().length > 0;
			$step.find(".start-oauth-btn").prop("disabled", !(has_id && has_secret));
		});

		// Enable complete button when code entered
		$step.find(".oauth-auth-code").on("input", () => {
			$step.find(".complete-reg-btn").prop("disabled", !$step.find(".oauth-auth-code").val().trim());
		});

		$step.find(".start-oauth-btn").on("click", () => this._start_oauth($step));
		$step.find(".complete-reg-btn").on("click", () => this._complete_registration($step));
	}

	_start_oauth($step) {
		const client_id = $step.find(".oauth-client-id").val().trim();
		const client_secret = $step.find(".oauth-client-secret").val().trim();
		const $btn = $step.find(".start-oauth-btn");
		const $result = $step.find(".oauth-result");

		$btn.prop("disabled", true).text(__("Generating link..."));
		$result.html("");

		frappe.xcall("catalog_bridge.google_setup.register.get_oauth_url", {
			platform_name: this.frm.doc.name,
			client_id: client_id,
			client_secret: client_secret,
			flow_type: "desktop",
		}).then((r) => {
			// Open auth URL in new tab
			window.open(r.auth_url, "_blank");

			// Show code input area
			$step.find(".oauth-code-area").show();
			$btn.text(__("Re-open Authorization Page")).prop("disabled", false);

			// Store credentials in state for complete_registration
			this.state.oauth_client_id = client_id;
			this.state.oauth_client_secret = client_secret;

			$result.html(`
				<div class="alert alert-info" role="alert">
					${__("A new tab opened for Google authorization. Sign in, authorize the app, then paste the code above.")}
				</div>
			`);
		}).catch((err) => {
			$btn.prop("disabled", false).text(__("Authorize with Google"));
			$result.html(`
				<div class="alert alert-danger" role="alert">${err.message || err}</div>
			`);
		});
	}

	_complete_registration($step) {
		const auth_code = $step.find(".oauth-auth-code").val().trim();
		const $btn = $step.find(".complete-reg-btn");
		const $result = $step.find(".oauth-result");

		$btn.prop("disabled", true).text(__("Registering..."));

		frappe.xcall("catalog_bridge.google_setup.register.complete_registration", {
			platform_name: this.frm.doc.name,
			auth_code: auth_code,
			client_id: this.state.oauth_client_id,
			client_secret: this.state.oauth_client_secret,
		}).then((r) => {
			if (r.success) {
				$result.html(`
					<div class="alert alert-success" role="alert">
						<strong>${__("Registration successful!")}</strong> ${r.message}
					</div>
				`);
				this._enable_next();
				$btn.hide();
			} else {
				$result.html(`
					<div class="alert alert-danger" role="alert">
						<strong>${__("Registration failed.")}</strong> ${r.error}
					</div>
				`);
				$btn.prop("disabled", false).text(__("Complete Registration"));
			}
		}).catch((err) => {
			$btn.prop("disabled", false).text(__("Complete Registration"));
			$result.html(`
				<div class="alert alert-danger" role="alert">${err.message || err}</div>
			`);
		});
	}

	// ─── Step 5: Data Source & Feed Config ───────────────────────────

	_render_step_5() {
		const $step = this.$steps.find('.wizard-step[data-step="5"]');
		const doc = this.frm.doc;

		$step.html(`
			<h5 style="margin-bottom:4px;">${__("Data Source & Feed Configuration")}</h5>
			<p class="text-muted" style="margin-bottom:15px;">
				${__("Select the API data source for product uploads and configure feed settings.")}
			</p>

			<div class="ds-loading" style="text-align:center; padding:20px;">
				<span class="text-muted">${__("Detecting data sources...")}</span>
			</div>

			<div class="ds-results" style="display:none;">
				<div class="ds-select-area" style="margin-bottom:15px;">
					<label class="control-label">${__("Data Source")}</label>
					<select class="form-control ds-select" style="max-width:500px;"></select>
				</div>

				<div class="ds-not-found alert alert-warning" style="display:none;" role="alert">
					<strong>${__("No API data source found.")}</strong>
					<p style="margin-top:5px;">${__("Create one in Merchant Center:")}</p>
					<ol style="padding-left:20px; line-height:2;">
						<li>${__("Go to")} <a href="https://merchants.google.com/mc/products/feeds" target="_blank">Merchant Center &gt; Products &gt; Feeds</a></li>
						<li>${__("Click")} <strong>${__("Add feed")}</strong> &gt; <strong>API</strong></li>
						<li>${__("Select your target country and language")}</li>
						<li>${__("Save, then come back and click Refresh below")}</li>
					</ol>
					<button class="btn btn-sm btn-default ds-refresh-btn" style="margin-top:5px;">${__("Refresh")}</button>
				</div>

				<div style="display:flex; gap:15px; margin-top:15px;">
					<div style="flex:1;">
						<label class="control-label">${__("Content Language")}</label>
						<input type="text" class="form-control feed-language" value="${doc.google_content_language || "en"}" placeholder="en" style="max-width:200px;">
					</div>
					<div style="flex:1;">
						<label class="control-label">${__("Feed Label")}</label>
						<input type="text" class="form-control feed-label" value="${doc.google_feed_label || "online"}" placeholder="online" style="max-width:200px;">
					</div>
				</div>

				<div style="display:flex; gap:15px; margin-top:15px;">
					<div style="flex:1;">
						<label class="control-label">${__("Frontend URL")}</label>
						<input type="text" class="form-control frontend-url" value="${doc.frontend_url || ""}" placeholder="https://yourstore.com">
					</div>
					<div style="flex:1;">
						<label class="control-label">${__("Price List")}</label>
						<div class="price-list-link"></div>
					</div>
				</div>

				<div style="text-align:center; margin-top:20px;">
					<button class="btn btn-default test-final-btn">${__("Test Connection")}</button>
				</div>

				<div class="final-test-result" style="margin-top:10px;"></div>
			</div>
		`);

		// Render price list link field
		const price_list_field = frappe.ui.form.make_control({
			df: {
				fieldtype: "Link",
				options: "Price List",
				fieldname: "wizard_price_list",
				placeholder: __("Select Price List"),
			},
			parent: $step.find(".price-list-link"),
			render_input: true,
		});
		price_list_field.set_value(doc.price_list || "");
		this.state.price_list_field = price_list_field;

		// Detect data sources
		this._detect_data_sources($step);

		$step.find(".ds-refresh-btn").on("click", () => this._detect_data_sources($step));
		$step.find(".test-final-btn").on("click", () => this._test_final_connection($step));

		// Enable finish when data source is selected
		$step.find(".ds-select").on("change", () => this._check_step5_complete($step));
		$step.find(".feed-language, .feed-label, .frontend-url").on("input", () => this._check_step5_complete($step));
	}

	_detect_data_sources($step) {
		$step.find(".ds-loading").show();
		$step.find(".ds-results").hide();

		frappe.xcall("catalog_bridge.google_setup.data_source.detect_data_sources", {
			platform_name: this.frm.doc.name,
		}).then((r) => {
			$step.find(".ds-loading").hide();
			$step.find(".ds-results").show();

			const $select = $step.find(".ds-select");
			$select.empty();

			if (r.data_sources && r.data_sources.length > 0) {
				$step.find(".ds-not-found").hide();
				$select.show();

				for (const ds of r.data_sources) {
					const label = ds.display_name ? `${ds.display_name} (${ds.type})` : ds.name;
					const selected = ds.name === r.recommended ? "selected" : "";
					$select.append(`<option value="${ds.name}" ${selected}>${label}</option>`);
				}
				this._check_step5_complete($step);
			} else {
				$step.find(".ds-not-found").show();
				$select.hide();

				if (r.error) {
					$step.find(".ds-not-found").append(`
						<div class="text-muted" style="margin-top:5px; font-size:12px;">${__("Error")}: ${r.error}</div>
					`);
				}
			}
		});
	}

	_check_step5_complete($step) {
		const ds = $step.find(".ds-select").val();
		if (ds) {
			this._enable_next();
		} else {
			this._disable_next();
		}
	}

	_save_step_5() {
		const $step = this.$steps.find('.wizard-step[data-step="5"]');
		const ds = $step.find(".ds-select").val();
		const lang = $step.find(".feed-language").val().trim() || "en";
		const feed = $step.find(".feed-label").val().trim() || "online";
		const frontend = $step.find(".frontend-url").val().trim();
		const price_list = this.state.price_list_field ? this.state.price_list_field.get_value() : "";

		if (ds) this.frm.set_value("google_data_source", ds);
		this.frm.set_value("google_content_language", lang);
		this.frm.set_value("google_feed_label", feed);
		if (frontend) this.frm.set_value("frontend_url", frontend);
		if (price_list) this.frm.set_value("price_list", price_list);

		this.frm.dirty();
		this.frm.save();
	}

	_test_final_connection($step) {
		const $btn = $step.find(".test-final-btn");
		const $result = $step.find(".final-test-result");

		$btn.prop("disabled", true).text(__("Testing..."));
		$result.html("");

		frappe.xcall("catalog_bridge.google_setup.validate.test_merchant_access", {
			platform_name: this.frm.doc.name,
		}).then((r) => {
			$btn.prop("disabled", false).text(__("Test Connection"));

			if (r.status === "success") {
				$result.html(`
					<div class="alert alert-success" role="alert">
						<strong>${__("Connection works!")}</strong>
						${r.data_sources.length} ${__("data source(s) accessible. Setup is complete.")}
					</div>
				`);
			} else {
				$result.html(`
					<div class="alert alert-danger" role="alert">
						<strong>${r.status}:</strong> ${r.error}
					</div>
				`);
			}
		}).catch((err) => {
			$btn.prop("disabled", false).text(__("Test Connection"));
			$result.html(`
				<div class="alert alert-danger" role="alert">${err.message || err}</div>
			`);
		});
	}
};

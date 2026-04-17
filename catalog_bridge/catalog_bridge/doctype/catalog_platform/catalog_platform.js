frappe.ui.form.on('Catalog Platform', {
	refresh: function(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Sync All Items"), function() {
				const d = new frappe.ui.Dialog({
					title: __("Sync All Items to {0}", [frm.doc.platform_name]),
					fields: [
						{
							fieldtype: "HTML",
							options: `<p>${__("This will push every published Website Item to the platform.")}</p>`,
						},
						{
							fieldname: "delete_orphans",
							fieldtype: "Check",
							label: __("Also delete orphan products from the platform"),
							default: 1,
							description: __("Products on {0} whose Website Item no longer exists (or is unpublished) will be removed. Uncheck to push only.", [frm.doc.platform_name]),
						},
					],
					primary_action_label: __("Sync Now"),
					primary_action: function(values) {
						d.hide();
						frappe.call({
							method: 'catalog_bridge.tasks.initial_sync',
							args: {
								platform_name: frm.doc.name,
								delete_orphans: values.delete_orphans ? 1 : 0,
							},
							freeze: true,
							freeze_message: __("Syncing all items..."),
							callback: function(r) {
								if (r.message) {
									frappe.msgprint({
										title: __("Sync Complete"),
										message: r.message,
										indicator: "green"
									});
								}
							}
						});
					},
				});
				d.show();
			});
		}

		// Google Merchant Center actions
		if (frm.doc.platform_type === "Google Merchant Center") {
			frm.add_custom_button(__("Setup Google Merchant"), function() {
				new catalog_bridge.GoogleSetupWizard(frm);
			}, __("Actions"));

			frm.add_custom_button(__("Refresh Google Feed"), function() {
				frappe.call({
					method: 'catalog_bridge.tasks.refresh_google_feed',
					args: { platform_name: frm.doc.name },
					freeze: true,
					freeze_message: __("Fetching products from Google..."),
					callback: function(r) {
						if (r.message) {
							frappe.msgprint({
								title: __("Feed Refreshed"),
								message: r.message + '<br><br><a href="/app/google-product-feed">' + __("View Google Product Feed") + '</a>',
								indicator: "green"
							});
						}
					}
				});
			}, __("Actions"));
		}
	}
});

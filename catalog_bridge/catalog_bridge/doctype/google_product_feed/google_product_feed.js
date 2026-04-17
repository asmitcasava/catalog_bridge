frappe.ui.form.on('Google Product Feed', {
	refresh: function(frm) {
		// Color-code the status indicator
		const status = frm.doc.google_status;
		const colors = {
			'Approved': 'green',
			'Disapproved': 'red',
			'Pending': 'orange',
			'Unknown': 'grey',
			'Removed': 'darkgrey',
		};
		if (status && colors[status]) {
			frm.page.set_indicator(status, colors[status]);
		}

		// Link to view product on Google
		if (frm.doc.link) {
			frm.add_custom_button(__("Open Product Link"), function() {
				window.open(frm.doc.link, "_blank");
			});
		}

		// Link to Website Item
		if (frm.doc.website_item) {
			frm.add_custom_button(__("View Website Item"), function() {
				frappe.set_route("Form", "Website Item", frm.doc.website_item);
			});
		}
	}
});

frappe.listview_settings['Google Product Feed'] = {
	get_indicator: function(doc) {
		const colors = {
			'Approved': [__('Approved'), 'green', 'google_status,=,Approved'],
			'Disapproved': [__('Disapproved'), 'red', 'google_status,=,Disapproved'],
			'Pending': [__('Pending'), 'orange', 'google_status,=,Pending'],
			'Unknown': [__('Unknown'), 'grey', 'google_status,=,Unknown'],
			'Removed': [__('Removed'), 'darkgrey', 'google_status,=,Removed'],
		};
		return colors[doc.google_status] || [__('Unknown'), 'grey', ''];
	}
};

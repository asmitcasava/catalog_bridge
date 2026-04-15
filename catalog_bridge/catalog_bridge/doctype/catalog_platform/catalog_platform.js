frappe.ui.form.on('Catalog Platform', {
    refresh: function(frm) {
        if (!frm.is_new()) {
            frm.add_custom_button(__("Sync All Items"), function() {
                frappe.confirm(
                    __("This will sync all published Website Items to {0}. Continue?", [frm.doc.platform_name]),
                    function() {
                        frappe.call({
                            method: 'catalog_bridge.tasks.initial_sync',
                            args: { platform_name: frm.doc.name },
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
                    }
                );
            });
        }
    }
});

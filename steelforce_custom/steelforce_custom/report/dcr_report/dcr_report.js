// Copyright (c) 2025, siva and contributors
// For license information, please see license.txt


frappe.query_reports["DCR Report"] = {
    filters: [
        {
            fieldname: "from_date",
            label: __("From Date"),
            fieldtype: "Date",
            reqd: 1,
            default: frappe.datetime.get_today()
        },
        {
            fieldname: "to_date",
            label: __("To Date"),
            fieldtype: "Date",
            reqd: 1,
            default: frappe.datetime.get_today()
        },
        {
            fieldname: "pos_profile",
            label: __("POS Profile"),
            fieldtype: "Link",
            options: "POS Profile",
        }
    ],

    tree: true,
    name_field: "name",
    parent_field: "parent",
    initial_depth: 0,

    onload: function (report) {
        frappe.db.get_list("POS Profile", {
            filters: [
                ["POS Profile User", "user", "=", frappe.session.user]
            ],
            fields: ["name"],
            limit: 1
        }).then(r => {
            if (!r || !r.length) {
                frappe.msgprint(__("No POS Profile linked to this user"));
                return;
            }

            const pos_profile = r[0].name;

            report.get_filter("pos_profile").set_value(pos_profile);
            report.refresh();
        });
    }
};

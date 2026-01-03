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
            options: "POS Profile"
        }
    ],

    tree: true,
    name_field: "name",
    parent_field: "parent",
    initial_depth: 0,

    onload: function (report) {

        /* ----------------------------------------------------
           Add SAFE Print Button (prevents orientation error)
        -----------------------------------------------------*/
        report.page.add_inner_button(__("Print"), function () {
            frappe.ui.get_print_settings(false, function (print_settings) {
                report.print_report(print_settings);
            });
        });

        /* ----------------------------------------------------
           Auto-set POS Profile linked to logged-in user
        -----------------------------------------------------*/
        frappe.db.get_list("POS Profile", {
            filters: [
                ["POS Profile User", "user", "=", frappe.session.user]
            ],
            fields: ["name"],
            limit: 1
        }).then(function (r) {
            if (!r || !r.length) {
                frappe.msgprint(__("No POS Profile linked to this user"));
                return;
            }

            report.get_filter("pos_profile").set_value(r[0].name);
            report.refresh();
        });
    }
};

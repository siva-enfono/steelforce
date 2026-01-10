// Copyright (c) 2026, siva and contributors
// For license information, please see license.txt


frappe.query_reports["DCR-All Branches"] = {
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
            fieldtype: "MultiSelectList",
            options: "POS Profile",
            get_data: function (txt) {
                return frappe.db.get_link_options("POS Profile", txt);
            }
        }
    ],

    tree: true,
    name_field: "name",
    parent_field: "parent",
    initial_depth: 0,

    onload: function (report) {

        /* SAFE PRINT BUTTON */
        report.page.add_inner_button(__("Print"), function () {
            frappe.ui.get_print_settings(false, function (print_settings) {
                report.print_report(print_settings);
            });
        });

        // ✅ Show ALL branches by default (no auto filter)
    }
};

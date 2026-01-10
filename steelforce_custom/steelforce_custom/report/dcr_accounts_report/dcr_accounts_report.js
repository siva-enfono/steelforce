// Copyright (c) 2026, siva and contributors
// For license information, please see license.txt


frappe.query_reports["DCR-Accounts Report"] = {
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
    ]
};

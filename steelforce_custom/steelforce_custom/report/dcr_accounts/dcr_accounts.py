# Copyright (c) 2026, siva
# For license information, please see license.txt

import frappe


def execute(filters=None):
    filters = filters or {}

    conditions = []
    values = {}

    # -------------------------
    # DATE FILTER
    # -------------------------
    if filters.get("from_date") and filters.get("to_date"):
        conditions.append("si.posting_date BETWEEN %(from_date)s AND %(to_date)s")
        values["from_date"] = filters["from_date"]
        values["to_date"] = filters["to_date"]

    # -------------------------
    # POS PROFILE MULTI SELECT
    # -------------------------
    if filters.get("pos_profile"):
        pos_profiles = filters.get("pos_profile")

        if isinstance(pos_profiles, str):
            pos_profiles = [p.strip() for p in pos_profiles.split(",") if p.strip()]

        conditions.append("si.pos_profile IN %(pos_profiles)s")
        values["pos_profiles"] = tuple(pos_profiles)

    where_clause = " AND ".join(conditions)
    if where_clause:
        where_clause = " AND " + where_clause

    # -------------------------
    # COLUMNS
    # -------------------------
    columns = [
        {"label": "Date", "fieldname": "posting_date", "fieldtype": "Date", "width": 110},
        {
            "label": "Branch",
            "fieldname": "pos_profile",
            "fieldtype": "Link",
            "options": "POS Profile",
            "width": 80,
        },
        {
            "label": "Invoice",
            "fieldname": "invoice",
            "fieldtype": "Link",
            "options": "Sales Invoice",
            "width": 120,
        },
        {
            "label": "Invoice Amount",
            "fieldname": "grand_total",
            "fieldtype": "Currency",
            "width": 140,
        },

        {"label": "Walk-in Cash", "fieldname": "walkin_cash", "fieldtype": "Currency", "width": 120},
        {"label": "Walk-in Card", "fieldname": "walkin_card", "fieldtype": "Currency", "width": 120},

        {"label": "Home Cash", "fieldname": "home_cash", "fieldtype": "Currency", "width": 120},
        {"label": "Home Card", "fieldname": "home_card", "fieldtype": "Currency", "width": 120},

        {"label": "HUNGER STATION", "fieldname": "hunger_station", "fieldtype": "Currency", "width": 150},
        {"label": "KEETA", "fieldname": "keeta", "fieldtype": "Currency", "width": 120},
        {"label": "JAHEZ", "fieldname": "jahez", "fieldtype": "Currency", "width": 120},
        {"label": "TO YOU", "fieldname": "to_you", "fieldtype": "Currency", "width": 120},
    ]

    # -------------------------
    # DATA QUERY
    # -------------------------
    data = frappe.db.sql(f"""
        SELECT
            si.posting_date,
            si.pos_profile,
            si.name AS invoice,
            si.grand_total,

            /* WALK-IN CASH */
            CASE
                WHEN si.customer = 'Walk-in Customer'
                 AND EXISTS (
                    SELECT 1 FROM `tabSales Invoice Payment` p
                    WHERE p.parent = si.name AND p.mode_of_payment LIKE 'Cash%%'
                 )
                THEN (IFNULL(si.paid_amount,0) - IFNULL(si.change_amount,0)) - IFNULL(card.card_amount,0)
                ELSE 0
            END AS walkin_cash,

            /* WALK-IN CARD */
            CASE
                WHEN si.customer = 'Walk-in Customer'
                THEN IFNULL(card.card_amount,0)
                ELSE 0
            END AS walkin_card,

            /* HOME CASH */
            CASE
                WHEN si.customer NOT IN ('HUNGER STATION','KETA','JAHEZ','TO YOU','Walk-in Customer')
                 AND EXISTS (
                    SELECT 1 FROM `tabSales Invoice Payment` p
                    WHERE p.parent = si.name AND p.mode_of_payment LIKE 'Cash%%'
                 )
                THEN (IFNULL(si.paid_amount,0) - IFNULL(si.change_amount,0)) - IFNULL(card.card_amount,0)
                ELSE 0
            END AS home_cash,

            /* HOME CARD */
            CASE
                WHEN si.customer NOT IN ('HUNGER STATION','KETA','JAHEZ','TO YOU','Walk-in Customer')
                THEN IFNULL(card.card_amount,0)
                ELSE 0
            END AS home_card,

            /* AGGREGATORS */
            CASE WHEN si.customer = 'HUNGER STATION' THEN si.grand_total ELSE 0 END AS hunger_station,
            CASE WHEN si.customer = 'KETA' THEN si.grand_total ELSE 0 END AS keeta,
            CASE WHEN si.customer = 'JAHEZ' THEN si.grand_total ELSE 0 END AS jahez,
            CASE WHEN si.customer = 'TO YOU' THEN si.grand_total ELSE 0 END AS to_you

        FROM `tabSales Invoice` si

        LEFT JOIN (
            SELECT parent, SUM(amount) AS card_amount
            FROM `tabSales Invoice Payment`
            WHERE mode_of_payment = 'Card'
            GROUP BY parent
        ) card ON card.parent = si.name

        WHERE si.docstatus = 1
        {where_clause}

        ORDER BY si.posting_date DESC, si.name DESC
    """, values, as_dict=True)

    return columns, data

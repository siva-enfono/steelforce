# Copyright (c) 2025, siva and contributors
# For license information, please see license.txt

import frappe


def color_parent_name(name):
    if name.startswith("Online Sales"):
        return f"<span style='color:#2ca02c; font-weight:600'>{name}</span>"
    if name.startswith("Home Sales"):
        return f"<span style='color:#ff7f0e; font-weight:600'>{name}</span>"
    if name.startswith("Counter Sales"):
        return f"<span style='color:#1f77b4; font-weight:600'>{name}</span>"
    return name


def execute(filters=None):
    filters = filters or {}

    from_date = filters.get("from_date")
    to_date = filters.get("to_date")
    pos_profile = filters.get("pos_profile")

    # -------------------------------------------------
    # COLUMNS
    # -------------------------------------------------
    columns = [
        {"fieldname": "name", "label": "Sales Type / Mode of Payment / Invoice", "fieldtype": "Data", "width": 360},
        {"fieldname": "amount", "label": "Amount", "fieldtype": "Currency", "width": 180},
        {"fieldname": "invoice", "label": "Invoice", "fieldtype": "Link", "options": "Sales Invoice", "width": 260},
    ]

    data = []
    grand_total = 0

    # -------------------------------------------------
    # 🔹 PARENTS (Sales Type + Mode)
    # -------------------------------------------------
    parents = frappe.db.sql("""
        SELECT
            CONCAT(
                CASE
                    WHEN si.customer IN ('HUNGER STATION','KETA','JAHEZ','TO YOU')
                        THEN 'Online Sales'
                    WHEN si.customer = 'Walk-in Customer'
                        THEN 'Counter Sales'
                    ELSE 'Home Sales'
                END,
                ' - ',
                IFNULL(sip.mode_of_payment, 'Credit Sale'),
                IF(si.is_return = 1, ' (Return)', '')
            ) AS parent_name,

            si.is_return,

            SUM(
                CASE
                    WHEN sip.mode_of_payment IS NULL
                        THEN si.grand_total
                    WHEN sip.mode_of_payment = 'Cash'
                        THEN si.grand_total
                             - IFNULL((
                                 SELECT SUM(x.amount)
                                 FROM `tabSales Invoice Payment` x
                                 WHERE x.parent = si.name
                                   AND x.mode_of_payment != 'Cash'
                             ),0)
                    ELSE sip.amount
                END
            ) AS amount

        FROM `tabSales Invoice` si
        LEFT JOIN `tabSales Invoice Payment` sip
            ON sip.parent = si.name
            AND sip.parenttype = 'Sales Invoice'
            AND sip.parentfield = 'payments'

        WHERE
            si.docstatus = 1
            AND si.pos_profile = %(pos_profile)s
            AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s

        GROUP BY parent_name, si.is_return
        ORDER BY parent_name
    """, filters, as_dict=True)

    # -------------------------------------------------
    # 🔹 BUILD TREE
    # -------------------------------------------------
    for p in parents:
        data.append({
            "name": color_parent_name(p.parent_name),
            "parent": None,
            "amount": p.amount,
            "indent": 0,
        })

        grand_total += p.amount or 0

        sales_type = p.parent_name.split(" - ")[0]
        mode_only = p.parent_name.split(" - ")[-1].replace(" (Return)", "")

        # -------------------------------------------------
        # 🔹 INVOICES (MODE-WISE FIX)
        # -------------------------------------------------
        invoices = frappe.db.sql("""
            SELECT
                si.name,
                CASE
                    WHEN %(mode)s = 'Credit Sale'
                        THEN si.grand_total

                    WHEN %(mode)s = 'Cash'
                        THEN si.grand_total
                             - IFNULL((
                                 SELECT SUM(x.amount)
                                 FROM `tabSales Invoice Payment` x
                                 WHERE x.parent = si.name
                                   AND x.mode_of_payment != 'Cash'
                             ),0)

                    ELSE sip.amount
                END AS amount

            FROM `tabSales Invoice` si
            LEFT JOIN `tabSales Invoice Payment` sip
                ON sip.parent = si.name
                AND sip.mode_of_payment = %(mode)s

            WHERE
                si.docstatus = 1
                AND si.pos_profile = %(pos_profile)s
                AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
                AND si.is_return = %(is_return)s

                AND (
                    (%(mode)s = 'Credit Sale' AND sip.name IS NULL)
                    OR sip.mode_of_payment = %(mode)s
                )

                AND (
                    (%(sales_type)s = 'Online Sales'
                        AND si.customer IN ('HUNGER STATION','KETA','JAHEZ','TO YOU'))
                    OR (%(sales_type)s = 'Counter Sales'
                        AND si.customer = 'Walk-in Customer')
                    OR (%(sales_type)s = 'Home Sales'
                        AND si.customer NOT IN (
                            'HUNGER STATION','KETA','JAHEZ','TO YOU','Walk-in Customer'))
                )

            ORDER BY si.name
        """, {
            **filters,
            "is_return": p.is_return,
            "mode": mode_only,
            "sales_type": sales_type,
        }, as_dict=True)

        for inv in invoices:
            if inv.amount:
                data.append({
                    "name": inv.name,
                    "invoice": inv.name,
                    "parent": p.parent_name,
                    "amount": inv.amount,
                    "indent": 1,
                })

    # -------------------------------------------------
    # 🔹 FINAL SUMMARY
    # -------------------------------------------------
    vat_amount = round(grand_total * 0.15 / 1.15, 2)
    total_wo_vat = round(grand_total - vat_amount, 2)

    data.extend([
        {"name": "<b>Total W/O VAT</b>", "amount": total_wo_vat, "indent": 0},
        {"name": "<b>Total VAT (15%)</b>", "amount": vat_amount, "indent": 0},
        {"name": "<b style='font-size:14px'>TOTAL</b>", "amount": grand_total, "indent": 0},
    ])

    return columns, data

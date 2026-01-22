# Copyright (c) 2025, siva and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import getdate, add_days
from datetime import datetime, time


def color_parent_name(name):
    if name.startswith("Online Sales"):
        return f"<span style='color:#000000; font-weight:600'>{name}</span>"
    if name.startswith("Home Sales"):
        return f"<span style='color:#000000; font-weight:600'>{name}</span>"
    if name.startswith("Counter Sales"):
        return f"<span style='color:#000000; font-weight:600'>{name}</span>"
    return name


def execute(filters=None):
    filters = filters or {}

    from_date = filters.get("from_date")
    to_date = filters.get("to_date")
    pos_profile = filters.get("pos_profile")

    # -------------------------------------------------
    # 🔹 BUSINESS DAY WINDOW (03:00 → 03:00)
    # -------------------------------------------------
    from_datetime = datetime.combine(getdate(from_date), time(3, 0, 0))
    to_datetime = datetime.combine(add_days(getdate(to_date), 1), time(3, 0, 0))

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

    total_cash_counter_home = 0
    total_card_counter_home = 0

    # -------------------------------------------------
    # 🔹 BASE DATA (PE > POS > CREDIT, MULTI MODE SPLIT)
    # -------------------------------------------------
    rows = frappe.db.sql("""
        SELECT
            si.name AS invoice,
            si.customer,
            si.is_return,
            si.grand_total,
            IFNULL(si.change_amount,0) AS change_amount,

            pe.mop  AS pe_mop,
            pe.amount AS pe_amount,

            pos.mop AS pos_mop,
            pos.amount AS pos_amount

        FROM `tabSales Invoice` si

        LEFT JOIN (
            SELECT
                per.reference_name AS invoice,
                pe.mode_of_payment AS mop,
                SUM(per.allocated_amount) AS amount
            FROM `tabPayment Entry Reference` per
            JOIN `tabPayment Entry` pe ON pe.name = per.parent
            WHERE per.reference_doctype = 'Sales Invoice'
              AND pe.docstatus = 1
            GROUP BY per.reference_name, pe.mode_of_payment
        ) pe ON pe.invoice = si.name

        LEFT JOIN (
            SELECT
                parent AS invoice,
                mode_of_payment AS mop,
                SUM(amount) AS amount
            FROM `tabSales Invoice Payment`
            GROUP BY parent, mode_of_payment
        ) pos ON pos.invoice = si.name

        WHERE
            si.docstatus = 1
            AND si.pos_profile = %(pos_profile)s
            AND TIMESTAMP(si.posting_date, si.posting_time)
                BETWEEN %(from_datetime)s AND %(to_datetime)s
    """, {
        "pos_profile": pos_profile,
        "from_datetime": from_datetime,
        "to_datetime": to_datetime,
    }, as_dict=True)

    # -------------------------------------------------
    # 🔹 NORMALIZE INTO SALES TYPE + MODE ROWS
    # -------------------------------------------------
    normalized = []

    for r in rows:

        if r.customer in ('HUNGER STATION','KETA','JAHEZ','TO YOU'):
            sales_type = "Online Sales"
        elif r.customer == "Walk-in Customer":
            sales_type = "Counter Sales"
        else:
            sales_type = "Home Sales"

        # RETURN → always grand total
        if r.is_return:
            normalized.append({
                "parent": f"{sales_type} - Return",
                "invoice": r.invoice,
                "mode": "Return",
                "amount": r.grand_total
            })
            continue

        # ---- PAYMENT ENTRY EXISTS → USE ONLY PE ----
        if r.pe_mop:
            amount = r.pe_amount or 0
            if r.pe_mop == "Cash":
                amount -= r.change_amount

            normalized.append({
                "parent": f"{sales_type} - {r.pe_mop}",
                "invoice": r.invoice,
                "mode": r.pe_mop,
                "amount": amount
            })
            continue

        # ---- POS MULTI MODE ----
        if r.pos_mop:
            amount = r.pos_amount or 0
            if r.pos_mop == "Cash":
                amount -= r.change_amount

            normalized.append({
                "parent": f"{sales_type} - {r.pos_mop}",
                "invoice": r.invoice,
                "mode": r.pos_mop,
                "amount": amount
            })
            continue

        # ---- CREDIT SALE ----
        normalized.append({
            "parent": f"{sales_type} - Credit Sale",
            "invoice": r.invoice,
            "mode": "Credit Sale",
            "amount": r.grand_total
        })

    # -------------------------------------------------
    # 🔹 GROUP BY PARENT
    # -------------------------------------------------
    parents = {}

    for r in normalized:
        parents.setdefault(r["parent"], []).append(r)

    # -------------------------------------------------
    # 🔹 BUILD TREE
    # -------------------------------------------------
    for parent, items in sorted(parents.items()):

        parent_amount = sum(i["amount"] for i in items)

        data.append({
            "name": color_parent_name(parent),
            "parent": None,
            "amount": parent_amount,
            "indent": 0
        })

        grand_total += parent_amount

        sales_type, mode_only = parent.split(" - ", 1)

        if sales_type in ("Counter Sales", "Home Sales"):
            if mode_only.startswith("Cash"):
                total_cash_counter_home += parent_amount
            elif mode_only not in ("Credit Sale", "Return"):
                total_card_counter_home += parent_amount

        for i in items:
            if i["amount"]:
                data.append({
                    "name": i["invoice"],
                    "invoice": i["invoice"],
                    "parent": parent,
                    "amount": i["amount"],
                    "indent": 1
                })

    # -------------------------------------------------
    # 🔹 FINAL SUMMARY
    # -------------------------------------------------
    vat_amount = round(grand_total * 0.15 / 1.15, 2)
    total_wo_vat = round(grand_total - vat_amount, 2)

    data.extend([
        {"name": "<b>Total Cash (Counter + Home)</b>", "amount": total_cash_counter_home, "indent": 0},
        {"name": "<b>Total Card (Counter + Home)</b>", "amount": total_card_counter_home, "indent": 0},
        {"name": "<b>Total W/O VAT</b>", "amount": total_wo_vat, "indent": 0},
        {"name": "<b>Total VAT (15%)</b>", "amount": vat_amount, "indent": 0},
        {"name": "<b style='font-size:14px'>TOTAL</b>", "amount": grand_total, "indent": 0},
    ])

    return columns, data

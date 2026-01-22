# Copyright (c) 2025, siva and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import getdate, add_days
from datetime import datetime, time


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
    # BUSINESS DAY WINDOW (03:00 → 03:00)
    # -------------------------------------------------
    from_datetime = datetime.combine(getdate(from_date), time(3, 0, 0))
    to_datetime = datetime.combine(add_days(getdate(to_date), 1), time(3, 0, 0))

    columns = [
        {"fieldname": "name", "label": "Sales Type / Mode / Invoice", "fieldtype": "Data", "width": 360},
        {"fieldname": "amount", "label": "Amount", "fieldtype": "Currency", "width": 180},
        {"fieldname": "invoice", "label": "Invoice", "fieldtype": "Link", "options": "Sales Invoice", "width": 260},
    ]

    data = []
    grand_total = 0
    total_cash_counter_home = 0
    total_card_counter_home = 0

    # -------------------------------------------------
    # 🔹 STEP 1: INVOICES WITH PAYMENT ENTRY (ONLY PE)
    # -------------------------------------------------
    pe_rows = frappe.db.sql("""
        SELECT
            si.name AS invoice,
            si.customer,
            si.is_return,
            si.grand_total,
            IFNULL(si.change_amount,0) AS change_amount,
            pe.mode_of_payment AS mop,
            SUM(per.allocated_amount) AS amount
        FROM `tabSales Invoice` si
        JOIN `tabPayment Entry Reference` per
            ON per.reference_name = si.name
           AND per.reference_doctype = 'Sales Invoice'
        JOIN `tabPayment Entry` pe
            ON pe.name = per.parent
           AND pe.docstatus = 1
        WHERE
            si.docstatus = 1
            AND si.pos_profile = %(pos_profile)s
            AND TIMESTAMP(si.posting_date, si.posting_time)
                BETWEEN %(from_datetime)s AND %(to_datetime)s
        GROUP BY si.name, pe.mode_of_payment
    """, {
        "pos_profile": pos_profile,
        "from_datetime": from_datetime,
        "to_datetime": to_datetime,
    }, as_dict=True)

    pe_invoices = {r.invoice for r in pe_rows}

    # -------------------------------------------------
    # 🔹 STEP 2: POS ONLY (NO PAYMENT ENTRY)
    # -------------------------------------------------
    pos_rows = frappe.db.sql("""
        SELECT
            si.name AS invoice,
            si.customer,
            si.is_return,
            si.grand_total,
            IFNULL(si.change_amount,0) AS change_amount,
            pos.mode_of_payment AS mop,
            SUM(pos.amount) AS amount
        FROM `tabSales Invoice` si
        JOIN `tabSales Invoice Payment` pos ON pos.parent = si.name
        WHERE
            si.docstatus = 1
            AND si.pos_profile = %(pos_profile)s
            AND TIMESTAMP(si.posting_date, si.posting_time)
                BETWEEN %(from_datetime)s AND %(to_datetime)s
            AND si.name NOT IN %(pe_invoices)s
        GROUP BY si.name, pos.mode_of_payment
    """, {
        "pos_profile": pos_profile,
        "from_datetime": from_datetime,
        "to_datetime": to_datetime,
        "pe_invoices": tuple(pe_invoices) or ("",),
    }, as_dict=True)

    pos_invoices = {r.invoice for r in pos_rows}

    # -------------------------------------------------
    # 🔹 STEP 3: CREDIT ONLY (NO PE, NO POS)
    # -------------------------------------------------
    credit_rows = frappe.db.sql("""
        SELECT
            si.name AS invoice,
            si.customer,
            si.is_return,
            si.grand_total,
            IFNULL(si.change_amount,0) AS change_amount
        FROM `tabSales Invoice` si
        WHERE
            si.docstatus = 1
            AND si.pos_profile = %(pos_profile)s
            AND TIMESTAMP(si.posting_date, si.posting_time)
                BETWEEN %(from_datetime)s AND %(to_datetime)s
            AND si.name NOT IN %(pe_pos)s
    """, {
        "pos_profile": pos_profile,
        "from_datetime": from_datetime,
        "to_datetime": to_datetime,
        "pe_pos": tuple(pe_invoices | pos_invoices) or ("",),
    }, as_dict=True)

    # -------------------------------------------------
    # 🔹 NORMALIZE
    # -------------------------------------------------
    normalized = []

    def get_sales_type(customer):
        if customer in ('HUNGER STATION','KETA','JAHEZ','TO YOU'):
            return "Online Sales"
        if customer == "Walk-in Customer":
            return "Counter Sales"
        return "Home Sales"

    for r in pe_rows + pos_rows:
        sales_type = get_sales_type(r.customer)

        amount = r.amount
        if r.mop == "Cash":
            amount -= r.change_amount

        normalized.append({
            "parent": f"{sales_type} - {r.mop}",
            "invoice": r.invoice,
            "mode": r.mop,
            "amount": amount,
            "sales_type": sales_type
        })

    for r in credit_rows:
        sales_type = get_sales_type(r.customer)
        normalized.append({
            "parent": f"{sales_type} - Credit Sale",
            "invoice": r.invoice,
            "mode": "Credit Sale",
            "amount": r.grand_total,
            "sales_type": sales_type
        })

    # -------------------------------------------------
    # 🔹 GROUP & BUILD TREE
    # -------------------------------------------------
    parents = {}
    for r in normalized:
        parents.setdefault(r["parent"], []).append(r)

    for parent, items in sorted(parents.items()):
        parent_amount = sum(i["amount"] for i in items)

        data.append({
            "name": color_parent_name(parent),
            "amount": parent_amount,
            "indent": 0
        })

        grand_total += parent_amount

        sales_type, mode_only = parent.split(" - ", 1)

        if sales_type in ("Counter Sales", "Home Sales"):
            if mode_only == "Cash":
                total_cash_counter_home += parent_amount
            elif mode_only != "Credit Sale":
                total_card_counter_home += parent_amount

        for i in items:
            data.append({
                "name": i["invoice"],
                "invoice": i["invoice"],
                "parent": parent,
                "amount": i["amount"],
                "indent": 1
            })

    # -------------------------------------------------
    # SUMMARY
    # -------------------------------------------------
    vat_amount = round(grand_total * 0.15 / 1.15, 2)
    total_wo_vat = round(grand_total - vat_amount, 2)

    data.extend([
        {"name": "<b>Total Cash (Counter + Home)</b>", "amount": total_cash_counter_home},
        {"name": "<b>Total Card (Counter + Home)</b>", "amount": total_card_counter_home},
        {"name": "<b>Total W/O VAT</b>", "amount": total_wo_vat},
        {"name": "<b>Total VAT (15%)</b>", "amount": vat_amount},
        {"name": "<b style='font-size:14px'>TOTAL</b>", "amount": grand_total},
    ])

    return columns, data

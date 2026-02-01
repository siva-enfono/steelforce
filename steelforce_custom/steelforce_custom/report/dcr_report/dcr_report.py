# Copyright (c) 2025, siva and contributors

import frappe
from frappe.utils import getdate, add_days
from datetime import datetime, time


def color_parent_name(name):
    return f"<span style='color:#000000; font-weight:600'>{name}</span>"


def execute(filters=None):
    filters = filters or {}

    from_date = filters.get("from_date")
    to_date = filters.get("to_date")
    pos_profile = filters.get("pos_profile")

    # -------------------------------------------------
    # POS PROFILE WAREHOUSE
    # -------------------------------------------------
    pos_warehouse = frappe.db.get_value("POS Profile", pos_profile, "warehouse")

    # -------------------------------------------------
    # BUSINESS DAY WINDOW (03:00 → 03:00)
    # -------------------------------------------------
    from_datetime = datetime.combine(getdate(from_date), time(3, 0, 0))
    to_datetime = datetime.combine(add_days(getdate(to_date), 1), time(3, 0, 0))

    columns = [
        {"fieldname": "name", "label": "Sales Type / Mode / Invoice / SO", "fieldtype": "Data", "width": 360},
        {"fieldname": "amount", "label": "Amount", "fieldtype": "Currency", "width": 180},
        {"fieldname": "invoice", "label": "Invoice", "fieldtype": "Link", "options": "Sales Invoice", "width": 200},
    ]

    data = []
    grand_total = 0
    total_cash_counter_home = 0
    total_card_counter_home = 0

    # -------------------------------------------------
    # 1️⃣ INVOICES IN POS WINDOW
    # -------------------------------------------------
    invoices = frappe.db.sql(
        """
        SELECT
            si.name,
            si.customer
        FROM `tabSales Invoice` si
        WHERE
            si.docstatus = 1
            AND si.pos_profile = %(pos_profile)s
            AND TIMESTAMP(si.posting_date, si.posting_time)
                BETWEEN %(from_datetime)s AND %(to_datetime)s
        """,
        {
            "pos_profile": pos_profile,
            "from_datetime": from_datetime,
            "to_datetime": to_datetime,
        },
        as_dict=True,
    )

    invoice_names = tuple(i.name for i in invoices) or ("",)
    invoice_customer = {i.name: i.customer for i in invoices}

    # -------------------------------------------------
    # 2️⃣ PAYMENT ENTRY REFERENCES (ERP SOURCE OF TRUTH)
    # -------------------------------------------------
    refs = frappe.db.sql(
        """
        SELECT
            per.reference_name AS invoice,
            per.advance_voucher_type,
            per.advance_voucher_no,
            per.allocated_amount,
            pe.mode_of_payment
        FROM `tabPayment Entry Reference` per
        JOIN `tabPayment Entry` pe ON pe.name = per.parent
        WHERE
            pe.docstatus = 1
            AND per.reference_doctype = 'Sales Invoice'
            AND per.reference_name IN %(invoices)s
        """,
        {"invoices": invoice_names},
        as_dict=True,
    )

    # -------------------------------------------------
    # NORMALIZE
    # -------------------------------------------------
    normalized = []

    def get_sales_type(customer):
        if customer in ("HUNGER STATION", "KETA", "JAHEZ", "TO YOU"):
            return "Online Sales"
        if customer == "Walk-in Customer":
            return "Counter Sales"
        return "Home Sales"

    for r in refs:
        customer = invoice_customer.get(r.invoice)
        sales_type = get_sales_type(customer)

        # 🔹 ADVANCE (FROM SALES ORDER)
        if r.advance_voucher_type == "Sales Order":
            normalized.append({
                "parent": f"{sales_type} - Sales Advance - {r.mode_of_payment}",
                "name": r.advance_voucher_no,   # Sales Order
                "amount": r.allocated_amount,
            })

        # 🔹 INVOICE PAYMENT (OUTSTANDING ONLY)
        else:
            normalized.append({
                "parent": f"{sales_type} - {r.mode_of_payment}",
                "name": r.invoice,
                "invoice": r.invoice,
                "amount": r.allocated_amount,
            })

    # -------------------------------------------------
    # BUILD TREE
    # -------------------------------------------------
    parents = {}
    for r in normalized:
        parents.setdefault(r["parent"], []).append(r)

    for parent, items in sorted(parents.items()):
        amt = sum(i["amount"] for i in items)

        data.append({
            "name": color_parent_name(parent),
            "amount": amt,
            "indent": 0,
        })

        grand_total += amt

        sales_type, mode_only = parent.split(" - ", 1)

        if sales_type in ("Counter Sales", "Home Sales"):
            if "Cash" in mode_only:
                total_cash_counter_home += amt
            elif "Sales Advance" not in mode_only:
                total_card_counter_home += amt

        for i in items:
            data.append({
                "name": i["name"],
                "invoice": i.get("invoice"),
                "amount": i["amount"],
                "indent": 1,
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

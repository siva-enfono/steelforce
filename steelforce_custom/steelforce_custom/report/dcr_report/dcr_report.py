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

    pos_warehouse = frappe.db.get_value("POS Profile", pos_profile, "warehouse")

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
    # 1️⃣ INVOICES
    # -------------------------------------------------
    invoices = frappe.db.sql("""
        SELECT
            si.name,
            si.customer,
            si.grand_total
        FROM `tabSales Invoice` si
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

    invoice_map = {i.name: i for i in invoices}
    invoice_names = tuple(invoice_map.keys()) or ("",)

    # -------------------------------------------------
    # 2️⃣ PAYMENT ENTRY REFERENCES
    # -------------------------------------------------
    refs = frappe.db.sql("""
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
            AND per.reference_name IN %(invoices)s
    """, {"invoices": invoice_names}, as_dict=True)

    # -------------------------------------------------
    # 3️⃣ POS PAYMENTS
    # -------------------------------------------------
    pos_payments = frappe.db.sql("""
        SELECT
            sip.parent AS invoice,
            sip.mode_of_payment,
            SUM(sip.amount) AS amount
        FROM `tabSales Invoice Payment` sip
        WHERE sip.parent IN %(invoices)s
        GROUP BY sip.parent, sip.mode_of_payment
    """, {"invoices": invoice_names}, as_dict=True)

    pos_map = {}
    for p in pos_payments:
        pos_map.setdefault(p.invoice, []).append(p)

    # -------------------------------------------------
    # NORMALIZE PER INVOICE
    # -------------------------------------------------
    normalized = []

    def get_sales_type(customer):
        if customer in ("HUNGER STATION", "KETA", "JAHEZ", "TO YOU"):
            return "Online Sales"
        if customer == "Walk-in Customer":
            return "Counter Sales"
        return "Home Sales"

    # group refs by invoice
    ref_map = {}
    for r in refs:
        ref_map.setdefault(r.invoice, []).append(r)

    for inv_name, inv in invoice_map.items():
        sales_type = get_sales_type(inv.customer)

        advance_total = 0
        paid_total = 0

        # ---- PAYMENT ENTRY ROWS ----
        for r in ref_map.get(inv_name, []):
            if r.advance_voucher_type == "Sales Order":
                normalized.append({
                    "parent": f"{sales_type} - Sales Advance - {r.mode_of_payment}",
                    "name": r.advance_voucher_no,
                    "amount": r.allocated_amount,
                })
                advance_total += r.allocated_amount
            else:
                normalized.append({
                    "parent": f"{sales_type} - {r.mode_of_payment}",
                    "name": inv_name,
                    "invoice": inv_name,
                    "amount": r.allocated_amount,
                })
                paid_total += r.allocated_amount

        # ---- POS PAYMENTS ----
        for p in pos_map.get(inv_name, []):
            normalized.append({
                "parent": f"{sales_type} - {p.mode_of_payment}",
                "name": inv_name,
                "invoice": inv_name,
                "amount": p.amount,
            })
            paid_total += p.amount

        # ---- CREDIT BALANCE ----
        balance = inv.grand_total - advance_total - paid_total
        if balance > 0:
            normalized.append({
                "parent": f"{sales_type} - Credit Sale",
                "name": inv_name,
                "invoice": inv_name,
                "amount": balance,
            })

    # -------------------------------------------------
    # BUILD TREE
    # -------------------------------------------------
    parents = {}
    for r in normalized:
        parents.setdefault(r["parent"], []).append(r)

    for parent, items in sorted(parents.items()):
        amt = sum(i["amount"] for i in items)

        data.append({"name": color_parent_name(parent), "amount": amt, "indent": 0})
        grand_total += amt

        sales_type, mode_only = parent.split(" - ", 1)

        if sales_type in ("Counter Sales", "Home Sales"):
            if "Cash" in mode_only:
                total_cash_counter_home += amt
            elif "Sales Advance" not in mode_only and mode_only != "Credit Sale":
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

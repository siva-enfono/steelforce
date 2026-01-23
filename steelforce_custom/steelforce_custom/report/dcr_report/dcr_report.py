# Copyright (c) 2025, siva and contributors
# For license information, please see license.txt

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
    # 🔹 INVOICE BASE DATA
    # -------------------------------------------------
    invoices = frappe.db.sql("""
        SELECT
            si.name AS invoice,
            si.customer,
            si.grand_total,
            si.is_return,
            GROUP_CONCAT(DISTINCT sii.sales_order) AS sales_orders

        FROM `tabSales Invoice` si
        LEFT JOIN `tabSales Invoice Item` sii ON sii.parent = si.name

        WHERE
            si.docstatus = 1
            AND si.pos_profile = %(pos_profile)s
            AND TIMESTAMP(si.posting_date, si.posting_time)
                BETWEEN %(from_datetime)s AND %(to_datetime)s

        GROUP BY si.name
    """, {
        "pos_profile": pos_profile,
        "from_datetime": from_datetime,
        "to_datetime": to_datetime,
    }, as_dict=True)

    invoice_names = tuple(i.invoice for i in invoices) or ("",)

    # -------------------------------------------------
    # 🔹 ADVANCE FROM PAYMENT ENTRY AGAINST SALES ORDER
    # -------------------------------------------------
    advances = frappe.db.sql("""
        SELECT
            per.reference_name AS sales_order,
            pe.mode_of_payment AS mop,
            mop_doc.type AS mop_type,
            SUM(per.allocated_amount) AS amount
        FROM `tabPayment Entry Reference` per
        JOIN `tabPayment Entry` pe ON pe.name = per.parent
        LEFT JOIN `tabMode of Payment` mop_doc ON mop_doc.name = pe.mode_of_payment
        WHERE
            per.reference_doctype = 'Sales Order'
            AND pe.docstatus = 1
            AND pe.posting_date BETWEEN %(from_date)s AND %(to_date)s
        GROUP BY per.reference_name, pe.mode_of_payment, mop_doc.type
    """, {
        "from_date": from_date,
        "to_date": to_date,
    }, as_dict=True)

    advance_map = {}
    for a in advances:
        advance_map.setdefault(a.sales_order, []).append(a)

    # -------------------------------------------------
    # 🔹 INVOICE PAYMENTS (PE)
    # -------------------------------------------------
    invoice_pe = frappe.db.sql("""
        SELECT
            per.reference_name AS invoice,
            pe.mode_of_payment AS mop,
            mop_doc.type AS mop_type,
            SUM(per.allocated_amount) AS amount
        FROM `tabPayment Entry Reference` per
        JOIN `tabPayment Entry` pe ON pe.name = per.parent
        LEFT JOIN `tabMode of Payment` mop_doc ON mop_doc.name = pe.mode_of_payment
        WHERE
            per.reference_doctype = 'Sales Invoice'
            AND pe.docstatus = 1
            AND per.reference_name IN %(invoices)s
        GROUP BY per.reference_name, pe.mode_of_payment, mop_doc.type
    """, {"invoices": invoice_names}, as_dict=True)

    # -------------------------------------------------
    # 🔹 INVOICE POS PAYMENTS
    # -------------------------------------------------
    invoice_pos = frappe.db.sql("""
        SELECT
            sip.parent AS invoice,
            sip.mode_of_payment AS mop,
            mop_doc.type AS mop_type,
            SUM(sip.amount) AS amount
        FROM `tabSales Invoice Payment` sip
        LEFT JOIN `tabMode of Payment` mop_doc ON mop_doc.name = sip.mode_of_payment
        WHERE sip.parent IN %(invoices)s
        GROUP BY sip.parent, sip.mode_of_payment, mop_doc.type
    """, {"invoices": invoice_names}, as_dict=True)

    pos_map = {}
    for p in invoice_pos:
        pos_map.setdefault(p.invoice, []).append(p)

    pe_map = {}
    for p in invoice_pe:
        pe_map.setdefault(p.invoice, []).append(p)

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

    for inv in invoices:

        sales_type = get_sales_type(inv.customer)

        # ---- ADVANCES FROM SALES ORDER ----
        if inv.sales_orders:
            for so in inv.sales_orders.split(","):
                for adv in advance_map.get(so, []):
                    normalized.append({
                        "parent": f"{sales_type} - Sales Advance - {adv.mop}",
                        "invoice": inv.invoice,
                        "amount": adv.amount,
                        "sales_type": sales_type,
                        "mode": adv.mop
                    })

        # total advance
        total_advance = sum(
            adv.amount for so in (inv.sales_orders or "").split(",")
            for adv in advance_map.get(so, [])
        )

        invoice_balance = inv.grand_total - total_advance

        # ---- PAYMENT ENTRY ON INVOICE ----
        if inv.invoice in pe_map:
            for p in pe_map[inv.invoice]:
                normalized.append({
                    "parent": f"{sales_type} - {p.mop}",
                    "invoice": inv.invoice,
                    "amount": p.amount,
                    "sales_type": sales_type,
                    "mode": p.mop
                })
            continue

        # ---- POS PAYMENT ----
        if inv.invoice in pos_map:
            for p in pos_map[inv.invoice]:
                normalized.append({
                    "parent": f"{sales_type} - {p.mop}",
                    "invoice": inv.invoice,
                    "amount": p.amount,
                    "sales_type": sales_type,
                    "mode": p.mop
                })
            continue

        # ---- CREDIT ----
        normalized.append({
            "parent": f"{sales_type} - Credit Sale",
            "invoice": inv.invoice,
            "amount": invoice_balance,
            "sales_type": sales_type,
            "mode": "Credit Sale"
        })

    # -------------------------------------------------
    # 🔹 GROUP & BUILD TREE
    # -------------------------------------------------
    parents = {}
    for r in normalized:
        parents.setdefault(r["parent"], []).append(r)

    for parent, items in sorted(parents.items()):
        parent_amount = sum(i["amount"] for i in items)

        data.append({"name": color_parent_name(parent), "amount": parent_amount, "indent": 0})
        grand_total += parent_amount

        sales_type, mode_only = parent.split(" - ", 1)

        if sales_type in ("Counter Sales", "Home Sales"):
            if "Cash" in mode_only:
                total_cash_counter_home += parent_amount
            elif "Sales Advance" not in mode_only and mode_only != "Credit Sale":
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

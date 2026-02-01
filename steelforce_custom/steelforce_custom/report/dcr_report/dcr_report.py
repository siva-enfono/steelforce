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
        {
            "fieldname": "invoice",
            "label": "Invoice",
            "fieldtype": "Link",
            "options": "Sales Invoice",
            "width": 200,
        },
    ]

    data = []
    grand_total = 0
    total_cash_counter_home = 0
    total_card_counter_home = 0

    # -------------------------------------------------
    # 1️⃣ SALES ADVANCES (PAYMENT ENTRY → SALES ORDER)
    # -------------------------------------------------
    advances = frappe.db.sql("""
        SELECT
            so.name AS sales_order,
            so.customer,
            pe.mode_of_payment AS mop,
            SUM(per.allocated_amount) AS amount
        FROM `tabPayment Entry Reference` per
        JOIN `tabPayment Entry` pe ON pe.name = per.parent
        JOIN `tabSales Order` so ON so.name = per.reference_name
        WHERE
            per.reference_doctype = 'Sales Order'
            AND pe.docstatus = 1
            AND so.set_warehouse = %(warehouse)s
            AND pe.posting_date BETWEEN %(from_date)s AND %(to_date)s
        GROUP BY so.name, pe.mode_of_payment
    """, {
        "warehouse": pos_warehouse,
        "from_date": from_date,
        "to_date": to_date,
    }, as_dict=True)

    # Map SO → advances
    advance_map = {}
    for a in advances:
        advance_map.setdefault(a.sales_order, []).append(a)

    # -------------------------------------------------
    # 2️⃣ INVOICES IN POS WINDOW
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

    invoice_names = tuple(i.name for i in invoices) or ("",)

    # -------------------------------------------------
    # 3️⃣ MAP INVOICE → SALES ORDER
    # -------------------------------------------------
    invoice_so = frappe.db.sql("""
        SELECT DISTINCT
            parent AS invoice,
            sales_order
        FROM `tabSales Invoice Item`
        WHERE parent IN %(invoices)s
          AND sales_order IS NOT NULL
    """, {"invoices": invoice_names}, as_dict=True)

    inv_so_map = {}
    for r in invoice_so:
        inv_so_map.setdefault(r.invoice, set()).add(r.sales_order)

    # -------------------------------------------------
    # 4️⃣ INVOICE PAYMENT ENTRY
    # -------------------------------------------------
    invoice_pe = frappe.db.sql("""
        SELECT
            per.reference_name AS invoice,
            pe.mode_of_payment AS mop,
            SUM(per.allocated_amount) AS amount
        FROM `tabPayment Entry Reference` per
        JOIN `tabPayment Entry` pe ON pe.name = per.parent
        WHERE
            per.reference_doctype = 'Sales Invoice'
            AND pe.docstatus = 1
            AND per.reference_name IN %(invoices)s
        GROUP BY per.reference_name, pe.mode_of_payment
    """, {"invoices": invoice_names}, as_dict=True)

    pe_map = {}
    for p in invoice_pe:
        pe_map.setdefault(p.invoice, []).append(p)

    # -------------------------------------------------
    # 5️⃣ POS PAYMENTS
    # -------------------------------------------------
    invoice_pos = frappe.db.sql("""
        SELECT
            sip.parent AS invoice,
            sip.mode_of_payment AS mop,
            SUM(sip.amount) AS amount
        FROM `tabSales Invoice Payment` sip
        WHERE sip.parent IN %(invoices)s
        GROUP BY sip.parent, sip.mode_of_payment
    """, {"invoices": invoice_names}, as_dict=True)

    pos_map = {}
    for p in invoice_pos:
        pos_map.setdefault(p.invoice, []).append(p)

    # -------------------------------------------------
    # NORMALIZE
    # -------------------------------------------------
    normalized = []

    def get_sales_type(customer):
        if customer in ('HUNGER STATION','KETA','JAHEZ','TO YOU'):
            return "Online Sales"
        if customer == "Walk-in Customer":
            return "Counter Sales"
        return "Home Sales"

    # ---- SALES ADVANCE (EVEN WITHOUT INVOICE) ----
    for a in advances:
        normalized.append({
            "parent": f"{get_sales_type(a.customer)} - Sales Advance - {a.mop}",
            "name": a.sales_order,
            "amount": a.amount,
            # no invoice key here
        })

    # ---- INVOICE FLOW ----
    for inv in invoices:

        sales_type = get_sales_type(inv.customer)

        # total advance linked to this invoice
        so_list = inv_so_map.get(inv.name, [])
        total_advance = sum(
            adv.amount
            for so in so_list
            for adv in advance_map.get(so, [])
        )

        balance = inv.grand_total - total_advance

        # Payment Entry on Invoice
        if inv.name in pe_map:
            for p in pe_map[inv.name]:
                normalized.append({
                    "parent": f"{sales_type} - {p.mop}",
                    "name": inv.name,
                    "invoice": inv.name,   # ✅ FIX
                    "amount": p.amount,
                })
            continue

        # POS Payment
        if inv.name in pos_map:
            for p in pos_map[inv.name]:
                normalized.append({
                    "parent": f"{sales_type} - {p.mop}",
                    "name": inv.name,
                    "invoice": inv.name,   # ✅ FIX
                    "amount": p.amount,
                })
            continue

        # Credit Sale
        normalized.append({
            "parent": f"{sales_type} - Credit Sale",
            "name": inv.name,
            "invoice": inv.name,       # ✅ FIX
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

        data.append({
            "name": color_parent_name(parent),
            "amount": amt,
            "indent": 0
        })

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
                "invoice": i.get("invoice"),  # ✅ invoice column works
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

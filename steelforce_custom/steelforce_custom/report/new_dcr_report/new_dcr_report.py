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
    # 🔹 PARENT LEVEL (PE > POS > CREDIT, CASH BY TYPE)
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
                IF(pe.mop IS NOT NULL, pe.mop, IF(pos.mop IS NOT NULL, pos.mop, 'Credit Sale')),
                IF(si.is_return = 1, ' (Return)', '')
            ) AS parent_name,

            si.is_return,

            SUM(
                CASE
                    -- PAYMENT ENTRY (never deduct change)
                    WHEN pe.amount IS NOT NULL THEN
                        pe.amount

                    -- POS PAYMENT (deduct change only if CASH TYPE)
                    WHEN pos.amount IS NOT NULL THEN
                        CASE
                            WHEN pos.mop_type = 'Cash'
                                THEN pos.amount - IFNULL(si.change_amount, 0)
                            ELSE pos.amount
                        END

                    -- CREDIT
                    ELSE si.grand_total
                END
            ) AS amount

        FROM `tabSales Invoice` si

        /* -------- POS PAYMENTS WITH MOP TYPE -------- */
        LEFT JOIN (
            SELECT
                sip.parent AS invoice,
                sip.mode_of_payment AS mop,
                mop_doc.type AS mop_type,
                SUM(sip.amount) AS amount
            FROM `tabSales Invoice Payment` sip
            LEFT JOIN `tabMode of Payment` mop_doc
                ON mop_doc.name = sip.mode_of_payment
            GROUP BY sip.parent, sip.mode_of_payment, mop_doc.type
        ) pos ON pos.invoice = si.name

        /* -------- PAYMENT ENTRY WITH MOP TYPE -------- */
        LEFT JOIN (
            SELECT
                per.reference_name AS invoice,
                pe.mode_of_payment AS mop,
                mop_doc.type AS mop_type,
                SUM(per.allocated_amount) AS amount
            FROM `tabPayment Entry Reference` per
            JOIN `tabPayment Entry` pe ON pe.name = per.parent
            LEFT JOIN `tabMode of Payment` mop_doc
                ON mop_doc.name = pe.mode_of_payment
            WHERE per.reference_doctype = 'Sales Invoice'
              AND pe.docstatus = 1
            GROUP BY per.reference_name, pe.mode_of_payment, mop_doc.type
        ) pe ON pe.invoice = si.name

        WHERE
            si.docstatus = 1
            AND si.pos_profile = %(pos_profile)s
            AND TIMESTAMP(si.posting_date, si.posting_time)
                BETWEEN %(from_datetime)s AND %(to_datetime)s

        GROUP BY parent_name, si.is_return
        ORDER BY parent_name
    """, {
        "pos_profile": pos_profile,
        "from_datetime": from_datetime,
        "to_datetime": to_datetime,
    }, as_dict=True)

    # -------------------------------------------------
    # 🔹 BUILD TREE
    # -------------------------------------------------
    for p in parents:
        data.append({
            "name": color_parent_name(p.parent_name),
            "parent": None,
            "amount": p.amount,
            "indent": 0
        })

        grand_total += p.amount or 0

        sales_type = p.parent_name.split(" - ")[0]
        mode_only = p.parent_name.split(" - ")[-1].replace(" (Return)", "")

        if sales_type in ("Counter Sales", "Home Sales"):
            # cash-type detected already via parent grouping
            if "Cash" in mode_only:
                total_cash_counter_home += p.amount or 0
            elif mode_only != "Credit Sale":
                total_card_counter_home += p.amount or 0

        # -------------------------------------------------
        # 🔹 INVOICE LEVEL (PE > POS > CREDIT, CASH BY TYPE)
        # -------------------------------------------------
        invoices = frappe.db.sql("""
            SELECT
                si.name,

                SUM(
                    CASE
                        WHEN pe.amount IS NOT NULL THEN
                            pe.amount

                        WHEN pos.amount IS NOT NULL THEN
                            CASE
                                WHEN pos.mop_type = 'Cash'
                                    THEN pos.amount - IFNULL(si.change_amount, 0)
                                ELSE pos.amount
                            END

                        ELSE si.grand_total
                    END
                ) AS amount

            FROM `tabSales Invoice` si

            LEFT JOIN (
                SELECT
                    sip.parent AS invoice,
                    sip.mode_of_payment AS mop,
                    mop_doc.type AS mop_type,
                    SUM(sip.amount) AS amount
                FROM `tabSales Invoice Payment` sip
                LEFT JOIN `tabMode of Payment` mop_doc
                    ON mop_doc.name = sip.mode_of_payment
                GROUP BY sip.parent, sip.mode_of_payment, mop_doc.type
            ) pos ON pos.invoice = si.name

            LEFT JOIN (
                SELECT
                    per.reference_name AS invoice,
                    pe.mode_of_payment AS mop,
                    mop_doc.type AS mop_type,
                    SUM(per.allocated_amount) AS amount
                FROM `tabPayment Entry Reference` per
                JOIN `tabPayment Entry` pe ON pe.name = per.parent
                LEFT JOIN `tabMode of Payment` mop_doc
                    ON mop_doc.name = pe.mode_of_payment
                WHERE per.reference_doctype = 'Sales Invoice'
                  AND pe.docstatus = 1
                GROUP BY per.reference_name, pe.mode_of_payment, mop_doc.type
            ) pe ON pe.invoice = si.name

            WHERE
                si.docstatus = 1
                AND si.pos_profile = %(pos_profile)s
                AND TIMESTAMP(si.posting_date, si.posting_time)
                    BETWEEN %(from_datetime)s AND %(to_datetime)s
                AND si.is_return = %(is_return)s

                AND (
                    (%(mode)s = 'Credit Sale' AND pe.mop IS NULL AND pos.mop IS NULL)
                    OR pe.mop = %(mode)s
                    OR pos.mop = %(mode)s
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

            GROUP BY si.name
            ORDER BY si.name
        """, {
            "pos_profile": pos_profile,
            "from_datetime": from_datetime,
            "to_datetime": to_datetime,
            "is_return": p.is_return,
            "mode": mode_only,
            "sales_type": sales_type
        }, as_dict=True)

        for inv in invoices:
            if inv.amount:
                data.append({
                    "name": inv.name,
                    "invoice": inv.name,
                    "parent": p.parent_name,
                    "amount": inv.amount,
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

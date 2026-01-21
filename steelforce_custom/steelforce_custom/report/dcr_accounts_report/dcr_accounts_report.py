# Copyright (c) 2026, siva
# For license information, please see license.txt

import frappe


def execute(filters=None):
    filters = filters or {}

    conditions = []
    values = {}

    # -------------------------
    # BUSINESS DAY (03:00 → 03:00)
    # -------------------------
    if filters.get("from_date") and filters.get("to_date"):
        conditions.append("""
            TIMESTAMP(si.posting_date, si.posting_time) BETWEEN
            TIMESTAMP(%(from_date)s, '03:00:00')
            AND
            TIMESTAMP(DATE_ADD(%(to_date)s, INTERVAL 1 DAY), '03:00:00')
        """)
        values["from_date"] = filters["from_date"]
        values["to_date"] = filters["to_date"]

    # -------------------------
    # POS PROFILE MULTI SELECT
    # -------------------------
    if filters.get("pos_profile"):
        pos_profiles = filters.get("pos_profile")

        if isinstance(pos_profiles, str):
            pos_profiles = [p.strip() for p in pos_profiles.split(",") if p.strip()]

        if pos_profiles:
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
        {"label": "Branch", "fieldname": "pos_profile", "fieldtype": "Link", "options": "POS Profile", "width": 80},
        {"label": "Invoice", "fieldname": "invoice", "fieldtype": "Link", "options": "Sales Invoice", "width": 120},
        {"label": "Invoice Amount", "fieldname": "grand_total", "fieldtype": "Currency", "width": 140},

        {"label": "Walk-in Cash", "fieldname": "walkin_cash", "fieldtype": "Currency", "width": 120},
        {"label": "Walk-in Card", "fieldname": "walkin_card", "fieldtype": "Currency", "width": 120},

        {"label": "Home Cash", "fieldname": "home_cash", "fieldtype": "Currency", "width": 120},
        {"label": "Home Card", "fieldname": "home_card", "fieldtype": "Currency", "width": 120},
        {"label": "Home Credit", "fieldname": "home_credit", "fieldtype": "Currency", "width": 120},

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

            /* =========================
               WALK-IN CASH (POS)
            ==========================*/
            CASE
                WHEN si.customer = 'Walk-in Customer'
                 AND (
                     (si.pos_profile = 'Saihat' AND EXISTS (
                         SELECT 1 FROM `tabSales Invoice Payment`
                         WHERE parent = si.name AND mode_of_payment = 'Cash-Saihat'
                     ))
                  OR (si.pos_profile = 'Faisaliya' AND EXISTS (
                         SELECT 1 FROM `tabSales Invoice Payment`
                         WHERE parent = si.name AND mode_of_payment = 'Cash-FA'
                     ))
                  OR (si.pos_profile = 'Doha' AND EXISTS (
                         SELECT 1 FROM `tabSales Invoice Payment`
                         WHERE parent = si.name AND mode_of_payment = 'Cash-Doha'
                     ))
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

            /* =========================
               HOME CASH (POS OR PAYMENT ENTRY)
            ==========================*/
            CASE
                WHEN si.customer NOT IN ('HUNGER STATION','KETA','JAHEZ','TO YOU','Walk-in Customer')
                 AND (
                     /* POS CASH */
                     (
                         (si.pos_profile = 'Saihat' AND EXISTS (
                             SELECT 1 FROM `tabSales Invoice Payment`
                             WHERE parent = si.name AND mode_of_payment = 'Cash-Saihat'
                         ))
                      OR (si.pos_profile = 'Faisaliya' AND EXISTS (
                             SELECT 1 FROM `tabSales Invoice Payment`
                             WHERE parent = si.name AND mode_of_payment = 'Cash-FA'
                         ))
                      OR (si.pos_profile = 'Doha' AND EXISTS (
                             SELECT 1 FROM `tabSales Invoice Payment`
                             WHERE parent = si.name AND mode_of_payment = 'Cash-Doha'
                         ))
                     )
                     /* PAYMENT ENTRY CASH */
                     OR pe_pay.mop = 'Cash'
                 )
                THEN
                    CASE
                        WHEN IFNULL(card.card_amount,0) > 0
                        THEN (IFNULL(si.paid_amount,0) - IFNULL(si.change_amount,0)) - IFNULL(card.card_amount,0)
                        ELSE IFNULL(pe_pay.paid_amount, si.grand_total)
                    END
                ELSE 0
            END AS home_cash,

            /* =========================
               HOME CARD (POS OR PAYMENT ENTRY)
            ==========================*/
            CASE
                WHEN si.customer NOT IN ('HUNGER STATION','KETA','JAHEZ','TO YOU','Walk-in Customer')
                 AND (
                     IFNULL(card.card_amount,0) > 0
                     OR pe_pay.mop = 'Card'
                 )
                THEN
                    CASE
                        WHEN IFNULL(card.card_amount,0) > 0
                        THEN card.card_amount
                        ELSE IFNULL(pe_pay.paid_amount, si.grand_total)
                    END
                ELSE 0
            END AS home_card,

            /* =========================
               HOME CREDIT (ONLY IF NO POS & NO PE)
            ==========================*/
            CASE
                WHEN si.customer NOT IN ('HUNGER STATION','KETA','JAHEZ','TO YOU','Walk-in Customer')
                 AND NOT EXISTS (
                    SELECT 1 FROM `tabSales Invoice Payment`
                    WHERE parent = si.name
                      AND mode_of_payment IN (
                          'Cash-Saihat','Cash-FA','Cash-Doha',
                          'Card-SA','Card-FA','Card-DO'
                      )
                 )
                 AND pe_pay.invoice IS NULL
                THEN si.grand_total
                ELSE 0
            END AS home_credit,

            /* =========================
               AGGREGATORS
            ==========================*/
            CASE WHEN si.customer = 'HUNGER STATION' THEN si.grand_total ELSE 0 END AS hunger_station,
            CASE WHEN si.customer = 'KETA' THEN si.grand_total ELSE 0 END AS keeta,
            CASE WHEN si.customer = 'JAHEZ' THEN si.grand_total ELSE 0 END AS jahez,
            CASE WHEN si.customer = 'TO YOU' THEN si.grand_total ELSE 0 END AS to_you

        FROM `tabSales Invoice` si

        /* -------- POS CARD AMOUNT -------- */
        LEFT JOIN (
            SELECT
                sip.parent AS invoice,
                SUM(sip.amount) AS card_amount
            FROM `tabSales Invoice Payment` sip
            JOIN `tabSales Invoice` si2 ON si2.name = sip.parent
            WHERE
                (si2.pos_profile = 'Saihat' AND sip.mode_of_payment IN ('Card-SA','Card-FA'))
                OR (si2.pos_profile = 'Faisaliya' AND sip.mode_of_payment = 'Card-FA')
                OR (si2.pos_profile = 'Doha' AND sip.mode_of_payment IN ('Card-DO','Card-FA'))
            GROUP BY sip.parent
        ) card ON card.invoice = si.name

        /* -------- PAYMENT ENTRY (FOR HOME CREDIT) -------- */
        LEFT JOIN (
            SELECT
                per.reference_name AS invoice,

                CASE
                    WHEN MAX(pe.mode_of_payment) LIKE 'Cash%%' THEN 'Cash'
                    WHEN MAX(pe.mode_of_payment) LIKE 'Card%%'
                      OR MAX(pe.mode_of_payment) LIKE 'Mada%%'
                      OR MAX(pe.mode_of_payment) LIKE 'Visa%%'
                        THEN 'Card'
                    ELSE MAX(pe.mode_of_payment)
                END AS mop,

                SUM(per.allocated_amount) AS paid_amount

            FROM `tabPayment Entry Reference` per
            JOIN `tabPayment Entry` pe ON pe.name = per.parent
            WHERE per.reference_doctype = 'Sales Invoice'
              AND pe.docstatus = 1
            GROUP BY per.reference_name
        ) pe_pay ON pe_pay.invoice = si.name

        WHERE si.docstatus = 1
        {where_clause}

        ORDER BY
            TIMESTAMP(si.posting_date, si.posting_time) DESC,
            si.name DESC
    """, values, as_dict=True)

    return columns, data

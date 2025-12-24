import frappe

def execute(filters=None):
    if not filters:
        filters = {}

    from_date = filters.get("from_date")
    to_date = filters.get("to_date")
    pos_profile = filters.get("pos_profile")

    # -------------------------------------------------
    # COLUMNS
    # -------------------------------------------------
    columns = [
        {
            "fieldname": "name",
            "label": "Sales Type / Mode of Payment / Invoice",
            "fieldtype": "Data",
            "width": 360
        },
        {
            "fieldname": "amount",
            "label": "Amount",
            "fieldtype": "Currency",
            "width": 180
        },
        {
            # hidden link field – ONLY used for invoices
            "fieldname": "invoice",
            "label": "Invoice",
            "fieldtype": "Link",
            "options": "Sales Invoice",
            "hidden": 1
        }
    ]

    data = []

    # -------------------------------------------------
    # 🔹 PARENTS → SALES TYPE + MODE OF PAYMENT
    # -------------------------------------------------
    parents = frappe.db.sql("""
        SELECT
            CASE
                WHEN si.is_return = 1 THEN
                    CONCAT(
                        CASE
                            WHEN si.customer = 'Home Sales Customer'
                                THEN 'Home Sales'
                            WHEN si.customer = 'Walk-in Customer'
                                THEN 'Counter Sales'
                            ELSE
                                'Online Sales'
                        END,
                        ' - ',
                        IFNULL(sip.mode_of_payment, 'Credit Sale'),
                        ' (Return)'
                    )
                ELSE
                    CONCAT(
                        CASE
                            WHEN si.customer = 'Home Sales Customer'
                                THEN 'Home Sales'
                            WHEN si.customer = 'Walk-in Customer'
                                THEN 'Counter Sales'
                            ELSE
                                'Online Sales'
                        END,
                        ' - ',
                        IFNULL(sip.mode_of_payment, 'Credit Sale')
                    )
            END AS parent_name,

            si.is_return,

            SUM(
                CASE
                    WHEN sip.mode_of_payment IS NULL
                        THEN IFNULL(si.grand_total, 0)
                    ELSE IFNULL(sip.amount, 0) - IFNULL(si.change_amount, 0)
                END
            ) AS amount

        FROM `tabSales Invoice` si
        LEFT JOIN `tabSales Invoice Payment` sip
            ON sip.parent = si.name
            AND sip.parenttype = 'Sales Invoice'
            AND sip.parentfield = 'payments'

        WHERE
            si.docstatus = 1
            AND si.is_pos = 1
            AND si.pos_profile = %(pos_profile)s
            AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s

        GROUP BY parent_name, si.is_return
        ORDER BY si.is_return ASC
    """, {
        "from_date": from_date,
        "to_date": to_date,
        "pos_profile": pos_profile
    }, as_dict=True)

    # -------------------------------------------------
    # BUILD TREE
    # -------------------------------------------------
    for p in parents:
        # 🔹 Parent row (plain text, NOT a link)
        data.append({
            "name": p.parent_name,
            "parent": None,
            "amount": p.amount,
            "indent": 0
        })

        # -------------------------------------------------
        # 🔹 CHILDREN → SALES INVOICES (CLICKABLE)
        # -------------------------------------------------
        invoices = frappe.db.sql("""
            SELECT
                si.name,
                si.grand_total
            FROM `tabSales Invoice` si
            LEFT JOIN `tabSales Invoice Payment` sip
                ON sip.parent = si.name
                AND sip.parenttype = 'Sales Invoice'
                AND sip.parentfield = 'payments'
            WHERE
                si.docstatus = 1
                AND si.is_pos = 1
                AND si.pos_profile = %(pos_profile)s
                AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
                AND si.is_return = %(is_return)s
                AND (
                    (%(mode)s LIKE '%%Credit Sale%%' AND sip.name IS NULL)
                    OR IFNULL(sip.mode_of_payment, 'Credit Sale') = %(mode_only)s
                )
            ORDER BY si.name
        """, {
            "from_date": from_date,
            "to_date": to_date,
            "pos_profile": pos_profile,
            "is_return": p.is_return,
            "mode": p.parent_name,
            "mode_only": p.parent_name.split(' - ')[-1].replace(' (Return)', '')
        }, as_dict=True)

        for inv in invoices:
            data.append({
                "name": inv.name,          # shown text
                "invoice": inv.name,       # actual clickable link
                "parent": p.parent_name,
                "amount": inv.grand_total,
                "indent": 1
            })

    return columns, data

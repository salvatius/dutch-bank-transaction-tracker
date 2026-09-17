import argparse
from datetime import datetime
import sqlite3

from openpyxl import Workbook
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter
from openpyxl.styles import PatternFill, Font
from db_helpers import BASE_DIR, DB_PATH, format_amount_nl, build_transaction_query, get_splits

EXPORTS_DIR = BASE_DIR / "exports"

def parse_args():
    parser = argparse.ArgumentParser(description="Export transactions to an Excel check file.")
    parser.add_argument("--from", dest="date_from", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to", dest="date_to", help="End date (YYYY-MM-DD)")
    parser.add_argument("--category", help="Filter by 'main_type/subcategory'")
    parser.add_argument("--uncategorized", action="store_true", help="Only uncategorized transactions")
    return parser.parse_args()


def build_query(args):
    query = """
        SELECT t.id, t.date, t.description, t.own_account, t.counter_account,
               t.code, t.direction, t.amount, t.mutation_type, t.notes,
               t.balance_after, t.category_id, c.main_type, c.subcategory
        FROM transactions t
        LEFT JOIN categories c ON t.category_id = c.id
        WHERE 1=1
    """
    params = []

    if args.date_from:
        query += " AND t.date >= ?"
        params.append(args.date_from)
    if args.date_to:
        query += " AND t.date <= ?"
        params.append(args.date_to)
    if args.uncategorized:
        query += " AND t.category_id IS NULL"
    if args.category:
        main_type, _, subcategory = args.category.partition("/")
        query += " AND c.main_type = ? AND c.subcategory = ?"
        params.append(main_type.strip())
        params.append(subcategory.strip())

    query += " ORDER BY t.date, t.id"
    return query, params

def get_splits(cursor, transaction_id):
    cursor.execute("""
        SELECT ts.amount, c.main_type, c.subcategory
        FROM transaction_splits ts
        JOIN categories c ON ts.category_id = c.id
        WHERE ts.transaction_id = ?
    """, (transaction_id,))
    return cursor.fetchall()

def get_category_lists(cursor):
    """Return (main_types, subcategories) - flat lists of distinct values."""
    cursor.execute("SELECT DISTINCT main_type FROM categories ORDER BY main_type")
    main_types = [row[0] for row in cursor.fetchall()]

    cursor.execute("SELECT DISTINCT subcategory FROM categories ORDER BY subcategory")
    subcategories = [row[0] for row in cursor.fetchall()]

    return main_types, subcategories

def export_transactions_excel(cursor, args):
    query, params = build_transaction_query(args)
    cursor.execute(query, params)
    transactions = cursor.fetchall()

    main_types, subcategories = get_category_lists(cursor)

    wb = Workbook()
    ws = wb.active
    ws.title = "Transactions"

    headers = [
        "Datum", "Rekening", "Naam / Omschrijving", "Tegenrekening", "Code",
        "Af Bij", "Bedrag (EUR)", "Mutatiesoort", "Mededelingen", "Saldo na mutatie",
        "income/expense", "category"
    ]

    ws.append(headers)

    row_num = 1  # header is row 1, data starts at row 2

    for (tx_id, date, description, own_account, counter_account, code,
         direction, amount, mutation_type, notes, balance_after,
         category_id, main_type, subcategory) in transactions:

        af_bij = "Af" if direction == "debit" else "Bij"
        splits = get_splits(cursor, tx_id)

        rows_for_this_tx = splits if splits else [(amount, main_type, subcategory)]

        for row_amount, row_main_type, row_subcategory in rows_for_this_tx:
            ws.append([
                date,
                own_account,
                description,
                counter_account,
                code,
                af_bij,
                format_amount_nl(row_amount),
                mutation_type,
                notes,
                format_amount_nl(balance_after) if balance_after is not None else "",
                row_main_type or "",
                row_subcategory or "",
            ])
            row_num += 1
    # --- color the dropdown columns light blue ---
    light_blue = PatternFill(start_color="D6E9F8", end_color="D6E9F8", fill_type="solid")

    for row in range(1, row_num + 1):  # includes header row
        ws.cell(row=row, column=11).fill = light_blue  # income/expense
        ws.cell(row=row, column=12).fill = light_blue  # category

    # --- bold headers ---
    bold_font = Font(bold=True)
    for col in range(1, len(headers) + 1):
        ws.cell(row=1, column=col).font = bold_font

    # --- autofilter across the whole data range ---
    last_col_letter = get_column_letter(len(headers))
    ws.auto_filter.ref = f"A1:{last_col_letter}{row_num}"

    # --- hidden helper sheet with the dropdown source lists ---
    lists_ws = wb.create_sheet("_lists")
    lists_ws.sheet_state = "hidden"

    for i, value in enumerate(main_types, start=1):
        lists_ws.cell(row=i, column=1, value=value)
    for i, value in enumerate(subcategories, start=1):
        lists_ws.cell(row=i, column=2, value=value)

    main_type_range = f"_lists!$A$1:$A${len(main_types)}"
    subcategory_range = f"_lists!$B$1:$B${len(subcategories)}"

    dv_main = DataValidation(type="list", formula1=f"={main_type_range}", allow_blank=True)
    dv_sub = DataValidation(type="list", formula1=f"={subcategory_range}", allow_blank=True)
    ws.add_data_validation(dv_main)
    ws.add_data_validation(dv_sub)

    # column 11 = "income/expense", column 12 = "category"
    dv_main.add(f"K2:K{row_num}")
    dv_sub.add(f"L2:L{row_num}")

    # reasonable column widths
    for col_num, header in enumerate(headers, start=1):
        col_letter = get_column_letter(col_num)
        ws.column_dimensions[col_letter].width = max(12, len(header) + 2)

    EXPORTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    output_path = EXPORTS_DIR / f"export_{timestamp}.xlsx"
    wb.save(output_path)

    return output_path, row_num - 1

if __name__ == "__main__":
    args = parse_args()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    output_path, row_count = export_transactions_excel(cursor, args)
    conn.close()

    print(f"Exported {row_count} rows to {output_path}")
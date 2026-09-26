import argparse
import csv
import sqlite3
from datetime import datetime
from db_helpers import BASE_DIR, DB_PATH, format_amount_nl, build_transaction_query, get_splits


EXPORTS_DIR = BASE_DIR / "exports"

def parse_args():
    parser = argparse.ArgumentParser(description="Export transactions to a CSV check file.")
    parser.add_argument("--from", dest="date_from", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to", dest="date_to", help="End date (YYYY-MM-DD)")
    parser.add_argument("--category", help="Filter by 'main_type/subcategory'")
    parser.add_argument("--uncategorized", action="store_true", help="Only uncategorized transactions")
    return parser.parse_args()

def export_transactions(cursor, args):
    query, params = build_transaction_query(args)
    cursor.execute(query, params)
    transactions = cursor.fetchall()

    EXPORTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    output_path = EXPORTS_DIR / f"export_{timestamp}.csv"

    fieldnames = [
        "Datum", "Naam / Omschrijving", "Rekening", "Tegenrekening", "Code",
        "Af Bij", "Bedrag (EUR)", "Mutatiesoort", "Mededelingen", "Saldo na mutatie",
        "income/expense", "group", "category"
    ]

    row_count = 0
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";", quoting=csv.QUOTE_ALL)
        writer.writeheader()

        for (tx_id, date, counter_party_name, own_account, counter_account, code,
             direction, amount, mutation_type, notes, balance_after,
             category_id, main_type, group_name, subcategory) in transactions:

            af_bij = "Af" if direction == "debit" else "Bij"
            splits = get_splits(cursor, tx_id)

            if splits:
                for split_amount, split_main_type, split_group_name, split_subcategory in splits:
                    writer.writerow({
                        "Datum": date,
                        "Naam / Omschrijving": counter_party_name,
                        "Rekening": own_account,
                        "Tegenrekening": counter_account,
                        "Code": code,
                        "Af Bij": af_bij,
                        "Bedrag (EUR)": format_amount_nl(split_amount),
                        "Mutatiesoort": mutation_type,
                        "Mededelingen": notes,
                        "Saldo na mutatie": format_amount_nl(balance_after) if balance_after is not None else "",
                        "income/expense": split_main_type,
                        "group": split_group_name,
                        "category": split_subcategory,
                    })
                    row_count += 1
            else:
                writer.writerow({
                    "Datum": date,
                    "Naam / Omschrijving": counter_party_name,
                    "Rekening": own_account,
                    "Tegenrekening": counter_account,
                    "Code": code,
                    "Af Bij": af_bij,
                    "Bedrag (EUR)": format_amount_nl(amount),
                    "Mutatiesoort": mutation_type,
                    "Mededelingen": notes,
                    "Saldo na mutatie": format_amount_nl(balance_after) if balance_after is not None else "",
                    "income/expense": main_type or "",
                    "group": group_name or "",
                    "category": subcategory or "",
                })
                row_count += 1

    return output_path, row_count

if __name__ == "__main__":
    args = parse_args()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    output_path, row_count = export_transactions(cursor, args)
    conn.close()

    print(f"Exported {row_count} rows to {output_path}")


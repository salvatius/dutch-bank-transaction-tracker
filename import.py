import json
import argparse
import sqlite3
from pathlib import Path
import csv
from datetime import datetime
import hashlib
from db_helpers import BASE_DIR, DB_PATH, get_category_label, describe_rule, create_new_category, get_schema_for_file

# This makes all paths relative to where THIS script lives,
# regardless of what folder you run it from.
SCHEMA_PATH = BASE_DIR / "schemas" / "ing.json"
IMPORT_PATH = BASE_DIR / "imports" / "ing_sample.csv"

class ImportAborted(Exception):
    """Raised when the user chooses to stop the import partway through."""
    pass


def load_schema(schema_path):
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)

def parse_args():
    parser = argparse.ArgumentParser(description="Import bank transactions.")
    parser.add_argument(
        "--auto-accept",
        action="store_true",
        help="Automatically accept rule-matched categorizations without confirmation."
    )
    return parser.parse_args()

def find_import_files(imports_dir):
    """Find CSV files not yet processed (i.e. without the .imported suffix)."""
    all_files = imports_dir.glob("*.csv")
    return [f for f in all_files if not f.name.endswith(".imported")]

def mark_as_imported(csv_path):
    new_path = csv_path.with_name(csv_path.name + ".imported")
    csv_path.rename(new_path)

def read_bank_csv(csv_path, schema):
    rows = []
    with open(csv_path, "r", encoding=schema["encoding"], newline="") as f:
        reader = csv.DictReader(
            f,
            delimiter=schema["delimiter"],
            quotechar=schema["quotechar"]
        )
        for row in reader:
            rows.append(row)
    return rows

def translate_row(raw_row, schema):
    """Convert one raw bank row into our canonical field names."""
    translated = {}
    for internal_field, bank_column in schema["field_mapping"].items():
        translated[internal_field] = raw_row.get(bank_column)
    return translated

def normalize_row(translated_row, schema):
    """Convert string values into proper types, using the schema's rules."""
    row = dict(translated_row)  # copy, so we don't mutate the original

    decimal_sep = schema["decimal_separator"]

    # --- amount: "26,89" -> 26.89 ---
    raw_amount = row["amount"]
    if decimal_sep != ".":
        raw_amount = raw_amount.replace(decimal_sep, ".")
    amount_value = float(raw_amount)

    # --- balance_after: "71,19" -> 71.19 (only if present) ---
    if row.get("balance_after"):
        raw_balance = row["balance_after"]
        if decimal_sep != ".":
            raw_balance = raw_balance.replace(decimal_sep, ".")
        row["balance_after"] = float(raw_balance)

    # --- date: "20260907" -> "2026-09-07" (ISO format, as text) ---
    date_obj = datetime.strptime(row["date"], schema["date_format"])
    row["date"] = date_obj.strftime("%Y-%m-%d")

    # --- direction + amount ---
    if schema.get("direction_from_amount_sign"):
        # geen aparte richting-kolom - het teken van het bedrag bepaalt het
        if amount_value < 0:
            row["direction"] = "debit"
        else:
            row["direction"] = "credit"
        row["amount"] = abs(amount_value)
    else:
        row["amount"] = amount_value
        direction_map = schema["direction_values"]
        for internal_value, bank_value in direction_map.items():
            if row["direction"] == bank_value:
                row["direction"] = internal_value
                break

    return row

def compute_hash(row, bank_name):
    """Build a stable fingerprint for duplicate detection."""
    fields = [
        bank_name,
        row["date"],
        row["description"] or "",
        row["own_account"] or "",
        row["counter_account"] or "",
        str(row["amount"]),
        row["direction"],
        row["notes"] or "",
    ]
    combined = "|".join(fields)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()

def hash_exists(cursor, row_hash):
    cursor.execute("SELECT 1 FROM transactions WHERE hash = ?", (row_hash,))
    return cursor.fetchone() is not None

def insert_transaction(cursor, row, bank_name):
    cursor.execute("""
        INSERT INTO transactions (
            hash, bank_name, date, description, own_account, counter_account,
            code, direction, amount, mutation_type, notes, balance_after,
            category_id, rule_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        row["hash"],
        bank_name,
        row["date"],
        row["description"],
        row["own_account"],
        row["counter_account"],
        row["code"],
        row["direction"],
        row["amount"],
        row["mutation_type"],
        row["notes"],
        row["balance_after"],
        row["category_id"],
        row["rule_id"],
    ))
    return cursor.lastrowid

def prompt_for_split(cursor, row, transaction_amount):
    """Interactively split a transaction's amount across multiple categories.
    Returns a list of (category_id, amount) tuples."""
    print(f"\n-- Splitting transaction (total: {transaction_amount}) --")
    splits = []
    remaining = transaction_amount

    while True:
        print(f"\nRemaining to allocate: {round(remaining, 2)}")
        cursor.execute("SELECT id, main_type, subcategory FROM categories ORDER BY main_type, subcategory")
        categories = cursor.fetchall()
        valid_ids = {cat_id for cat_id, _, _ in categories}
        for cat_id, main_type, subcategory in categories:
            print(f"  [{cat_id}] {main_type} / {subcategory}")

        cat_choice = input("Category ID for this split: ").strip()
        if not cat_choice.isdigit() or int(cat_choice) not in valid_ids:
            print(f"'{cat_choice}' is not a valid category ID.")
            continue
        split_category_id = int(cat_choice)

        amount_choice = input("Amount for this split: ").strip()
        try:
            split_amount = float(amount_choice.replace(",", "."))
        except ValueError:
            print(f"'{amount_choice}' is not a valid amount.")
            continue

        splits.append((split_category_id, split_amount))
        remaining = round(remaining - split_amount, 2)

        if remaining <= 0:
            break

        more = input("Add another split? (y/n): ").strip().lower()
        if more != "y":
            break

    total_entered = round(sum(amount for _, amount in splits), 2)
    if total_entered != round(transaction_amount, 2):
        print(f"\nSplits total {total_entered}, but transaction is {round(transaction_amount, 2)}. "
              f"They must match exactly.")
        print("Let's redo this split from scratch.")
        return prompt_for_split(cursor, row, transaction_amount)

    return splits

def save_splits(cursor, transaction_id, splits):
    """Save split rows and update the parent transaction's category_id to the largest split."""
    for category_id, amount in splits:
        cursor.execute(
            "INSERT INTO transaction_splits (transaction_id, category_id, amount) VALUES (?, ?, ?)",
            (transaction_id, category_id, amount)
        )

    largest_category_id = max(splits, key=lambda s: s[1])[0]
    cursor.execute(
        "UPDATE transactions SET category_id = ? WHERE id = ?",
        (largest_category_id, transaction_id)
    )

def find_matching_rule(cursor, row):
    """Return (category_id, rule_id) if a rule matches this row, else (None, None)."""
    cursor.execute("""
        SELECT id, category_id FROM rules ORDER BY priority DESC, id ASC
    """)
    all_rules = cursor.fetchall()

    for rule_id, category_id in all_rules:
        cursor.execute(
            "SELECT field, match_type, value, value2 FROM rule_conditions WHERE rule_id = ?",
            (rule_id,)
        )
        conditions = cursor.fetchall()

        if all(condition_matches(row, field, match_type, value, value2)
               for field, match_type, value, value2 in conditions):
            return category_id, rule_id

    return None, None

def condition_matches(row, field, match_type, value, value2=None):
    row_value = row.get(field)
    if row_value is None:
        return False

    if match_type == "contains":
        return value.lower() in str(row_value).lower()

    if match_type == "exact":
        return str(row_value) == value

    # Everything below is a numeric comparison - only valid for 'amount'
    if field != "amount":
        return False

    try:
        numeric_value = float(row_value)
        compare_to = float(value)
    except (TypeError, ValueError):
        return False

    if match_type == "gt":
        return numeric_value > compare_to
    elif match_type == "lt":
        return numeric_value < compare_to
    elif match_type == "gte":
        return numeric_value >= compare_to
    elif match_type == "lte":
        return numeric_value <= compare_to
    elif match_type == "between":
        try:
            upper = float(value2)
        except (TypeError, ValueError):
            return False
        return compare_to <= numeric_value <= upper

    return False

def prompt_for_category(cursor, row):
    """Ask the user to categorize an unmatched transaction, optionally creating a rule."""
    print("\n--- Uncategorized transaction ---")
    print(f"Date:        {row['date']}")
    print(f"Description: {row['description']}")
    print(f"Amount:      {row['amount']} ({row['direction']})")
    print(f"Notes:       {row['notes']}")

    if row["direction"] == "debit":
        suggested_type = "uitgaven"
    elif row["direction"] == "credit":
        suggested_type = "inkomen"
    else:
        suggested_type = None

    show_all = False
    chosen_id = None

    while chosen_id is None:
        if suggested_type and not show_all:
            cursor.execute(
                "SELECT id, main_type, subcategory FROM categories "
                "WHERE main_type = ? OR main_type = 'transfer' "
                "ORDER BY main_type, subcategory",
                (suggested_type,)
            )
        else:
            cursor.execute(
                "SELECT id, main_type, subcategory FROM categories ORDER BY main_type, subcategory"
            )
        categories = cursor.fetchall()
        valid_ids = {cat_id for cat_id, _, _ in categories}

        for cat_id, main_type, subcategory in categories:
            print(f"  [{cat_id}] {main_type} / {subcategory}")
        if suggested_type and not show_all:
                    print("  [N] Create a new category")
                    print("  [X] Split this transaction across multiple categories")
                    print("  [S] Skip this transaction (leave uncategorized, stop import)")

        choice = input("Category ID: ").strip()

        if choice.upper() == "A" and suggested_type and not show_all:
            show_all = True
            continue

        if choice.upper() == "N":
            new_id = create_new_category(cursor)
            if new_id is not None:
                chosen_id = new_id
            continue

        if choice.upper() == "X":
            return "SPLIT", None

        if choice.upper() == "S":
            raise ImportAborted("User chose to stop the import.")

        if not choice.isdigit() or int(choice) not in valid_ids:
            print(f"'{choice}' is not a valid category ID. Please pick one from the list.")
            continue

        chosen_id = int(choice)

        create_rule = input("Create a rule from this? (y/n): ").strip().lower()
    if create_rule == "y":
        rule_conditions_to_add = []

        while True:
            print("\nAdd a condition. Match on which field?")
            print("  [1] description")
            print("  [2] notes")
            print("  [3] counter_account")
            print("  [4] own_account")
            print("  [5] amount")
            print("  [6] direction")
            field_choice = input("Choice: ").strip()
            field_map = {
                "1": "description", "2": "notes", "3": "counter_account",
                "4": "own_account", "5": "amount", "6": "direction",
            }
            field = field_map.get(field_choice)
            if field is None:
                print("Invalid choice, try again.")
                continue

            if field == "amount":
                print("Match type? [1] exact  [2] greater than  [3] less than  "
                      "[4] greater or equal  [5] less or equal  [6] between")
                mt_choice = input("Choice: ").strip()
                mt_map = {"1": "exact", "2": "gt", "3": "lt", "4": "gte", "5": "lte", "6": "between"}
                match_type = mt_map.get(mt_choice, "exact")

                value = input("Amount value (e.g. 26.89): ").strip()
                value2 = None
                if match_type == "between":
                    value2 = input("Upper bound: ").strip()

            elif field == "direction":
                print("Match value? [1] debit  [2] credit")
                dir_choice = input("Choice: ").strip()
                value = "debit" if dir_choice == "1" else "credit"
                match_type = "exact"
                value2 = None

            else:
                suggested_value = row.get(field, "")
                value = input(f"Value to match (contains) [{suggested_value}]: ").strip()
                if not value:
                    value = suggested_value
                match_type = "contains"
                value2 = None

            rule_conditions_to_add.append((field, match_type, value, value2))

            more = input("Add another condition to this rule? (y/n): ").strip().lower()
            if more != "y":
                break

        cursor.execute(
            "INSERT INTO rules (category_id, priority) VALUES (?, ?)",
            (chosen_id, 0)
        )
        rule_id = cursor.lastrowid
        for field, match_type, value, value2 in rule_conditions_to_add:
            cursor.execute(
                "INSERT INTO rule_conditions (rule_id, field, match_type, value, value2) VALUES (?, ?, ?, ?, ?)",
                (rule_id, field, match_type, value, value2)
            )

        return chosen_id, rule_id

    return chosen_id, None

def process_file(csv_path, schema, cursor, auto_accept=False):
    print(f"\n=== Processing {csv_path.name} (bank: {schema['bank_name']}) ===")
    raw_rows = read_bank_csv(csv_path, schema)
    print(f"Read {len(raw_rows)} rows")

    inserted_count = 0
    skipped_count = 0

    for raw_row in raw_rows:
        translated = translate_row(raw_row, schema)
        normalized = normalize_row(translated, schema)
        row_hash = compute_hash(normalized, schema["bank_name"])
        normalized["hash"] = row_hash

        if hash_exists(cursor, row_hash):
            skipped_count += 1
            continue

        category_id, rule_id = find_matching_rule(cursor, normalized)

        if category_id is None:
            category_id, rule_id = prompt_for_category(cursor, normalized)
        elif auto_accept:
            label = get_category_label(cursor, category_id)
            rule_desc = describe_rule(cursor, rule_id)
            print(f"Auto: {normalized['description']} -> {label}  (rule: {rule_desc})")
        else:
            label = get_category_label(cursor, category_id)
            rule_desc = describe_rule(cursor, rule_id)
            print(f"\nAuto-categorized: {normalized['description']}")
            print(f"  -> {label}  (matched rule: {rule_desc})")
            confirm = input("Accept? (y = accept, n = choose different category, x = split): ").strip().lower()
            if confirm == "x":
                category_id, rule_id = "SPLIT", None
            elif confirm != "y":
                category_id, rule_id = prompt_for_category(cursor, normalized)

        normalized["category_id"] = category_id
        normalized["rule_id"] = rule_id

        if category_id == "SPLIT":
            normalized["category_id"] = None
            transaction_id = insert_transaction(cursor, normalized, schema["bank_name"])
            splits = prompt_for_split(cursor, normalized, normalized["amount"])
            save_splits(cursor, transaction_id, splits)
        else:
            insert_transaction(cursor, normalized, schema["bank_name"])

        inserted_count += 1

    print(f"Inserted: {inserted_count}, Skipped (duplicates): {skipped_count}")

if __name__ == "__main__":
    args = parse_args()

    imports_dir = BASE_DIR / "imports"
    schemas_dir = BASE_DIR / "schemas"

    files_to_process = find_import_files(imports_dir)

    if not files_to_process:
        print("No new files to import.")
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()

        for csv_path in files_to_process:
            schema_path = get_schema_for_file(csv_path, schemas_dir)
            if schema_path is None:
                print(f"Skipping {csv_path.name}: geen schema gevonden of gekozen.")
                continue

            schema = load_schema(schema_path)
            try:
                process_file(csv_path, schema, cursor, auto_accept=args.auto_accept)
                conn.commit()
                mark_as_imported(csv_path)
            except ImportAborted:
                print(f"\nImport stopped by user during {csv_path.name}.")
                conn.commit()
                print("Rows processed so far in this file were saved. File was NOT marked as imported — rerun to continue where you left off.")
                break

        conn.close()
import json
import sqlite3
from pathlib import Path
import csv
from datetime import datetime
import hashlib

# This makes all paths relative to where THIS script lives,
# regardless of what folder you run it from.
BASE_DIR = Path(__file__).parent

DB_PATH = BASE_DIR / "finance.db"
SCHEMA_PATH = BASE_DIR / "schemas" / "ing.json"
IMPORT_PATH = BASE_DIR / "imports" / "ing_sample.csv"


def load_schema(schema_path):
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)

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

    # --- amount: "26,89" -> 26.89 ---
    raw_amount = row["amount"]
    decimal_sep = schema["decimal_separator"]
    if decimal_sep != ".":
        raw_amount = raw_amount.replace(decimal_sep, ".")
    row["amount"] = float(raw_amount)

    # --- balance_after: "71,19" -> 71.19 (only if present) ---
    if row.get("balance_after"):
        raw_balance = row["balance_after"]
        if decimal_sep != ".":
            raw_balance = raw_balance.replace(decimal_sep, ".")
        row["balance_after"] = float(raw_balance)

    # --- date: "20260907" -> "2026-09-07" (ISO format, as text) ---
    date_obj = datetime.strptime(row["date"], schema["date_format"])
    row["date"] = date_obj.strftime("%Y-%m-%d")

    # --- direction: "Af" -> "debit", "Bij" -> "credit" ---
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
def find_matching_rule(cursor, row):
    """Return (category_id, rule_id) if a rule matches this row, else (None, None)."""
    cursor.execute("""
        SELECT id, category_id FROM rules ORDER BY priority DESC, id ASC
    """)
    all_rules = cursor.fetchall()

    for rule_id, category_id in all_rules:
        cursor.execute(
            "SELECT field, match_type, value FROM rule_conditions WHERE rule_id = ?",
            (rule_id,)
        )
        conditions = cursor.fetchall()

        if all(condition_matches(row, field, match_type, value)
               for field, match_type, value in conditions):
            return category_id, rule_id

    return None, None


def condition_matches(row, field, match_type, value):
    row_value = row.get(field)
    if row_value is None:
        return False
    row_value = str(row_value)

    if match_type == "exact":
        return row_value == value
    elif match_type == "contains":
        return value.lower() in row_value.lower()
    return False

def prompt_for_category(cursor, row):
    """Ask the user to categorize an unmatched transaction, optionally creating a rule."""
    print("\n--- Uncategorized transaction ---")
    print(f"Date:        {row['date']}")
    print(f"Description: {row['description']}")
    print(f"Amount:      {row['amount']} ({row['direction']})")
    print(f"Notes:       {row['notes']}")

    cursor.execute("SELECT id, main_type, subcategory FROM categories ORDER BY main_type, subcategory")
    categories = cursor.fetchall()
    for cat_id, main_type, subcategory in categories:
        print(f"  [{cat_id}] {main_type} / {subcategory}")

    chosen_id = int(input("Category ID: ").strip())

    create_rule = input("Create a rule from this? (y/n): ").strip().lower()
    if create_rule == "y":
        print("Match on which field?")
        print("  [1] description")
        print("  [2] notes")
        print("  [3] counter_account")
        field_choice = input("Choice: ").strip()
        field_map = {"1": "description", "2": "notes", "3": "counter_account"}
        field = field_map.get(field_choice, "description")

        suggested_value = row.get(field, "")
        value = input(f"Value to match (contains) [{suggested_value}]: ").strip()
        if not value:
            value = suggested_value

        cursor.execute(
            "INSERT INTO rules (category_id, priority) VALUES (?, ?)",
            (chosen_id, 0)
        )
        rule_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO rule_conditions (rule_id, field, match_type, value) VALUES (?, ?, ?, ?)",
            (rule_id, field, "contains", value)
        )
        return chosen_id, rule_id

    return chosen_id, None

if __name__ == "__main__":
    schema = load_schema(SCHEMA_PATH)
    raw_rows = read_bank_csv(IMPORT_PATH, schema)
    print(f"Read {len(raw_rows)} rows")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

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
        else:
            print(f"\nAuto-categorized: {normalized['description']} -> category_id {category_id} (via rule {rule_id})")
            confirm = input("Accept? (y = accept, n = choose different category): ").strip().lower()
            if confirm != "y":
                category_id, rule_id = prompt_for_category(cursor, normalized)

        normalized["category_id"] = category_id
        normalized["rule_id"] = rule_id

        insert_transaction(cursor, normalized, schema["bank_name"])
        inserted_count += 1

    conn.commit()
    conn.close()

    print(f"\nInserted: {inserted_count}, Skipped (duplicates): {skipped_count}")
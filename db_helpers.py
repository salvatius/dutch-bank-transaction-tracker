import sqlite3
from pathlib import Path
import json
import csv
import re
from collections import Counter

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "finance.db"
KNOWN_ACCOUNTS_PATH = BASE_DIR / "known_accounts.json"
IBAN_PATTERN = re.compile(r'^NL\d{2}[A-Z]{4}\d{10}$')


def get_connection():
    """Open a connection with foreign key enforcement on."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def format_amount_nl(amount):
    """26.89 -> '26,89'   |   1234.5 -> '1.234,50'"""
    formatted = f"{amount:,.2f}"
    formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
    return formatted


def get_category_label(cursor, category_id):
    cursor.execute("SELECT main_type, group_name, subcategory FROM categories WHERE id = ?", (category_id,))
    result = cursor.fetchone()
    return f"{result[0]} / {result[1]} / {result[2]}" if result else "unknown category"


def describe_rule(cursor, rule_id):
    cursor.execute(
        "SELECT field, match_type, value, value2 FROM rule_conditions WHERE rule_id = ?",
        (rule_id,)
    )
    conditions = cursor.fetchall()
    parts = []
    for field, match_type, value, value2 in conditions:
        if match_type == "contains":
            parts.append(f"{field} contains '{value}'")
        elif match_type == "exact":
            parts.append(f"{field} = '{value}'")
        elif match_type == "gt":
            parts.append(f"{field} > {value}")
        elif match_type == "lt":
            parts.append(f"{field} < {value}")
        elif match_type == "gte":
            parts.append(f"{field} >= {value}")
        elif match_type == "lte":
            parts.append(f"{field} <= {value}")
        elif match_type == "between":
            parts.append(f"{field} between {value} and {value2}")
    return " AND ".join(parts)


def build_transaction_query(args):
    query = """
        SELECT t.id, t.date, t.counter_party_name, t.own_account, t.counter_account,
               t.code, t.direction, t.amount, t.mutation_type, t.notes,
               t.balance_after, t.category_id, c.main_type, c.group_name, c.subcategory
        FROM transactions t
        LEFT JOIN categories c ON t.category_id = c.id
        WHERE 1=1
    """
    params = []

    date_from = getattr(args, "date_from", None)
    date_to = getattr(args, "date_to", None)
    category = getattr(args, "category", None)
    uncategorized = getattr(args, "uncategorized", False)
    account = getattr(args, "account", None)

    if date_from:
        query += " AND t.date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND t.date <= ?"
        params.append(date_to)
    if uncategorized:
        query += " AND t.category_id IS NULL"
    if category:
        parts = category.split("/")
        if len(parts) == 3:
            main_type, group_name, subcategory = (p.strip() for p in parts)
            query += " AND c.main_type = ? AND c.group_name = ? AND c.subcategory = ?"
            params.extend([main_type, group_name, subcategory])
    if account:
        query += " AND t.own_account = ?"
        params.append(account)

    query += " ORDER BY t.date, t.id"
    return query, params


def get_splits(cursor, transaction_id):
    cursor.execute("""
        SELECT ts.amount, c.main_type, c.group_name, c.subcategory
        FROM transaction_splits ts
        JOIN categories c ON ts.category_id = c.id
        WHERE ts.transaction_id = ?
    """, (transaction_id,))
    return cursor.fetchall()

def create_new_category(cursor):
    """Interactively create a new category. Returns its id, or None if cancelled."""
    print("\n-- New category --")
    print("  [1] inkomen")
    print("  [2] uitgaven")
    print("  [3] transfer")
    print("  [C] Cancel")
    type_choice = input("Main type: ").strip().upper()

    type_map = {"1": "inkomen", "2": "uitgaven", "3": "transfer"}
    if type_choice == "C" or type_choice not in type_map:
        return None
    main_type = type_map[type_choice]

    cursor.execute(
        "SELECT DISTINCT group_name FROM categories WHERE main_type = ? ORDER BY group_name",
        (main_type,)
    )
    existing_groups = [row[0] for row in cursor.fetchall()]

    if existing_groups:
        print(f"\nBestaande groepen binnen '{main_type}':")
        for i, g in enumerate(existing_groups, start=1):
            print(f"  [{i}] {g}")
        print("  [N] Nieuwe groep")
        group_choice = input("Groep: ").strip()
        if group_choice.isdigit() and 1 <= int(group_choice) <= len(existing_groups):
            group_name = existing_groups[int(group_choice) - 1]
        else:
            group_name = input("Naam nieuwe groep: ").strip()
    else:
        group_name = input("Groepnaam: ").strip()

    if not group_name:
        print("Groepnaam mag niet leeg zijn. Geannuleerd.")
        return None

    subcategory = input("Subcategorienaam: ").strip()
    if not subcategory:
        print("Subcategorienaam mag niet leeg zijn. Geannuleerd.")
        return None

    try:
        cursor.execute(
            "INSERT INTO categories (main_type, group_name, subcategory) VALUES (?, ?, ?)",
            (main_type, group_name, subcategory)
        )
    except sqlite3.IntegrityError:
        print(f"'{main_type} / {group_name} / {subcategory}' bestaat al.")
        cursor.execute(
            "SELECT id FROM categories WHERE main_type = ? AND group_name = ? AND subcategory = ?",
            (main_type, group_name, subcategory)
        )
        return cursor.fetchone()[0]

    new_id = cursor.lastrowid
    print(f"Aangemaakt [{new_id}] {main_type} / {group_name} / {subcategory}")
    return new_id

def load_known_accounts(path=KNOWN_ACCOUNTS_PATH):
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_known_accounts(known_accounts, path=KNOWN_ACCOUNTS_PATH):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(known_accounts, f, indent=4, ensure_ascii=False)

def detect_own_account(csv_path, encoding="utf-8"):
    """Vind de kolom waarin dezelfde IBAN-achtige waarde op vrijwel elke
    regel voorkomt - dat is de 'eigen rekening'-kolom, ongeacht schema."""
    with open(csv_path, "r", encoding=encoding, newline="", errors="ignore") as f:
        reader = csv.reader(f, delimiter=";", quotechar='"')
        rows = list(reader)

    if not rows:
        return None

    total_rows = len(rows)
    column_values = {}  # kolomindex -> Counter van IBAN-achtige waarden

    for row in rows:
        for col_index, value in enumerate(row):
            value = value.strip()
            if IBAN_PATTERN.match(value):
                column_values.setdefault(col_index, Counter())[value] += 1

    best_value = None
    best_ratio = 0.0

    for col_index, counter in column_values.items():
        value, count = counter.most_common(1)[0]
        ratio = count / total_rows
        if ratio > best_ratio:
            best_ratio = ratio
            best_value = value

    if best_ratio >= 0.5:
        return best_value
    return None

def get_schema_for_file(csv_path, schemas_dir):
    """Bepaal het schema via het gedetecteerde eigen rekeningnummer.
    Vraagt en onthoudt bij een nog-onbekende rekening."""
    known_accounts = load_known_accounts()
    own_account = detect_own_account(csv_path)

    if own_account and own_account in known_accounts:
        return schemas_dir / known_accounts[own_account]

    print(f"\nOnbekend rekeningnummer in {csv_path.name}.")
    if own_account:
        print(f"Gedetecteerd rekeningnummer: {own_account}")
        confirm = input("Is dit correct? (y/n): ").strip().lower()
        if confirm != "y":
            own_account = input("Rekeningnummer (IBAN): ").strip()
    else:
        own_account = input("Kon geen rekeningnummer detecteren. Voer IBAN handmatig in: ").strip()

    available_schemas = sorted(f.name for f in schemas_dir.glob("*.json"))
    if not available_schemas:
        print("Geen schema's gevonden in schemas/.")
        return None

    print("Beschikbare schema's:")
    for i, s in enumerate(available_schemas, start=1):
        print(f"  [{i}] {s}")
    choice = input("Welk schema hoort hierbij? ").strip()

    if choice.isdigit() and 1 <= int(choice) <= len(available_schemas):
        schema_file = available_schemas[int(choice) - 1]
        known_accounts[own_account] = schema_file
        save_known_accounts(known_accounts)
        print(f"Onthouden: {own_account} -> {schema_file}")
        return schemas_dir / schema_file

    print("Ongeldige keuze.")
    return None

def get_opening_balance(cursor, account_number):
    cursor.execute(
        "SELECT opening_date, opening_balance FROM account_balances WHERE account_number = ?",
        (account_number,)
    )
    result = cursor.fetchone()
    if result is None:
        return None

    opening_date, opening_balance = result
    if not opening_date or opening_balance in (None, ""):
        return None

    try:
        opening_balance = float(str(opening_balance).replace(",", "."))
    except ValueError:
        return None

    return opening_date, opening_balance

def set_opening_balance(cursor, account_number, opening_date, opening_balance):
    cursor.execute("""
        INSERT INTO account_balances (account_number, opening_date, opening_balance)
        VALUES (?, ?, ?)
        ON CONFLICT(account_number) DO UPDATE SET
            opening_date = excluded.opening_date,
            opening_balance = excluded.opening_balance
    """, (account_number, opening_date, opening_balance))

def calculate_balance(cursor, account_number, as_of_date=None):
    """Bereken het saldo van een rekening op een gegeven datum (of de meest
    recente bekende transactiedatum als geen datum is opgegeven)."""
    result = get_opening_balance(cursor, account_number)
    if result is None:
        return None
    opening_date, opening_balance = result

    if as_of_date is None:
        cursor.execute(
            "SELECT MAX(date) FROM transactions WHERE own_account = ?",
            (account_number,)
        )
        latest = cursor.fetchone()[0]
        as_of_date = latest if latest else opening_date

    if as_of_date >= opening_date:
        cursor.execute("""
            SELECT direction, amount FROM transactions
            WHERE own_account = ? AND date > ? AND date <= ?
        """, (account_number, opening_date, as_of_date))
        rows = cursor.fetchall()
        net = sum(amount if direction == "credit" else -amount for direction, amount in rows)
        return opening_balance + net
    else:
        cursor.execute("""
            SELECT direction, amount FROM transactions
            WHERE own_account = ? AND date > ? AND date <= ?
        """, (account_number, as_of_date, opening_date))
        rows = cursor.fetchall()
        net = sum(amount if direction == "credit" else -amount for direction, amount in rows)
        return opening_balance - net

def get_opening_balance_date_only(cursor, account_number):
    result = get_opening_balance(cursor, account_number)
    return result[0] if result else None

def get_category_lists(cursor):
    """Return (main_types, group_names, subcategories) - flat lists of distinct values."""
    cursor.execute("SELECT DISTINCT main_type FROM categories ORDER BY main_type")
    main_types = [row[0] for row in cursor.fetchall()]

    cursor.execute("SELECT DISTINCT group_name FROM categories ORDER BY group_name")
    group_names = [row[0] for row in cursor.fetchall()]

    cursor.execute("SELECT DISTINCT subcategory FROM categories ORDER BY subcategory")
    subcategories = [row[0] for row in cursor.fetchall()]

    return main_types, group_names, subcategories
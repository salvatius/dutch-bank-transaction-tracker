import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "finance.db"


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
    cursor.execute("SELECT main_type, subcategory FROM categories WHERE id = ?", (category_id,))
    result = cursor.fetchone()
    return f"{result[0]} / {result[1]}" if result else "unknown category"


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
    """Build a filtered transaction query + params, from a namespace with
    date_from, date_to, category, uncategorized attributes (any may be missing/None)."""
    query = """
        SELECT t.id, t.date, t.description, t.own_account, t.counter_account,
               t.code, t.direction, t.amount, t.mutation_type, t.notes,
               t.balance_after, t.category_id, c.main_type, c.subcategory
        FROM transactions t
        LEFT JOIN categories c ON t.category_id = c.id
        WHERE 1=1
    """
    params = []

    date_from = getattr(args, "date_from", None)
    date_to = getattr(args, "date_to", None)
    category = getattr(args, "category", None)
    uncategorized = getattr(args, "uncategorized", False)

    if date_from:
        query += " AND t.date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND t.date <= ?"
        params.append(date_to)
    if uncategorized:
        query += " AND t.category_id IS NULL"
    if category:
        main_type, _, subcategory = category.partition("/")
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
    subcategory = input("New subcategory name: ").strip()
    if not subcategory:
        print("Subcategory name cannot be empty. Cancelled.")
        return None

    try:
        cursor.execute(
            "INSERT INTO categories (main_type, subcategory) VALUES (?, ?)",
            (main_type, subcategory)
        )
    except sqlite3.IntegrityError:
        print(f"'{main_type} / {subcategory}' already exists.")
        cursor.execute(
            "SELECT id FROM categories WHERE main_type = ? AND subcategory = ?",
            (main_type, subcategory)
        )
        return cursor.fetchone()[0]

    new_id = cursor.lastrowid
    print(f"Created category [{new_id}] {main_type} / {subcategory}")
    return new_id


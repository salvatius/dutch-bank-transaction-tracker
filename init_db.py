import sqlite3
import csv
from db_helpers import BASE_DIR, DB_PATH

CATEGORIES_CSV_PATH = BASE_DIR / "categories_starter.csv"

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        main_type TEXT NOT NULL CHECK (main_type IN ('inkomen', 'uitgaven', 'transfer')),
        group_name TEXT NOT NULL,
        subcategory TEXT NOT NULL,
        UNIQUE (main_type, group_name, subcategory)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id INTEGER NOT NULL,
        priority INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (category_id) REFERENCES categories(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rule_conditions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_id INTEGER NOT NULL,
        field TEXT NOT NULL CHECK (field IN ('description', 'notes', 'amount', 'counter_account', 'own_account', 'direction')),
        match_type TEXT NOT NULL CHECK (match_type IN ('exact', 'contains', 'gt', 'lt', 'gte', 'lte', 'between')),
        value TEXT NOT NULL,
        value2 TEXT,
        FOREIGN KEY (rule_id) REFERENCES rules(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hash TEXT NOT NULL UNIQUE,
        bank_name TEXT NOT NULL,
        date TEXT NOT NULL,
        description TEXT,
        own_account TEXT,
        counter_account TEXT,
        code TEXT,
        direction TEXT NOT NULL CHECK (direction IN ('debit', 'credit')),
        amount REAL NOT NULL,
        mutation_type TEXT,
        notes TEXT,
        balance_after REAL,
        category_id INTEGER,
        rule_id INTEGER,
        FOREIGN KEY (category_id) REFERENCES categories(id),
        FOREIGN KEY (rule_id) REFERENCES rules(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS transaction_splits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_id INTEGER NOT NULL,
        category_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        FOREIGN KEY (transaction_id) REFERENCES transactions(id),
        FOREIGN KEY (category_id) REFERENCES categories(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS account_balances (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_number TEXT NOT NULL UNIQUE,
        opening_date TEXT NOT NULL,
        opening_balance REAL NOT NULL
    )
    """,
]

STARTER_CATEGORIES = [
    ("inkomen", "werk", "salaris"),
    ("inkomen", "werk", "verkopen"),
    ("uitgaven", "huishouden", "boodschappen"),
    ("uitgaven", "vaste lasten", "horeca"),
    ("uitgaven", "vervoer", "benzine"),
    ("uitgaven", "persoonlijk", "roken"),
    ("uitgaven", "vaste lasten", "afbetaling lening"),
    ("transfer", "sparen", "naar spaarrekening"),
]

def load_categories_from_csv(path):
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter=";")
        rows = list(reader)

    start = 1 if rows and rows[0][0].strip().lower() == "main_type" else 0
    categories = [
        (row[0].strip(), row[1].strip(), row[2].strip())
        for row in rows[start:]
        if len(row) >= 3 and row[0].strip() and row[1].strip() and row[2].strip()
    ]
    return categories

def init_database():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    for statement in SCHEMA_STATEMENTS:
        cursor.execute(statement)

    cursor.execute("SELECT COUNT(*) FROM categories")
    existing_count = cursor.fetchone()[0]

    if existing_count == 0:
        csv_categories = load_categories_from_csv(CATEGORIES_CSV_PATH)
        if csv_categories:
            confirm = input(
                f"{len(csv_categories)} categorieën gevonden in categories_starter.csv. Importeren? (y/n): "
            ).strip().lower()
            if confirm == "y":
                cursor.executemany(
                    "INSERT INTO categories (main_type, group_name, subcategory) VALUES (?, ?, ?)",
                    csv_categories
                )
                print(f"{len(csv_categories)} categorieën geïmporteerd.")
            else:
                print("Geen categorieën toegevoegd.")
        else:
            add_starters = input(
                "Geen categories_starter.csv gevonden. Standaard voorbeeldcategorieën toevoegen? (y/n): "
            ).strip().lower()
            if add_starters == "y":
                cursor.executemany(
                    "INSERT INTO categories (main_type, group_name, subcategory) VALUES (?, ?, ?)",
                    STARTER_CATEGORIES
                )
                print(f"{len(STARTER_CATEGORIES)} startcategorieën toegevoegd.")
            else:
                print("Geen categorieën toegevoegd. Gebruik manage_categories.py om ze zelf aan te maken.")
    else:
        print(f"{existing_count} categorie(ën) al aanwezig, startcategorieën overgeslagen.")

    conn.commit()
    conn.close()
    print(f"\nDatabase geïnitialiseerd: {DB_PATH}")


if __name__ == "__main__":
    init_database()
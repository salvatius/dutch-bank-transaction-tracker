import sqlite3
from db_helpers import DB_PATH, get_category_label, format_amount_nl


def search_transactions(cursor):
    print("\nZoek op: [1] beschrijving  [2] transactie-ID  [3] datum (YYYY-MM-DD)")
    choice = input("Keuze: ").strip()

    if choice == "1":
        term = input("Zoekterm in beschrijving: ").strip()
        cursor.execute("""
            SELECT id, date, counter_party_name, amount, direction, category_id
            FROM transactions
            WHERE counter_party_name LIKE ?
            ORDER BY date DESC
        """, (f"%{term}%",))
    elif choice == "2":
        tx_id = input("Transactie-ID: ").strip()
        if not tx_id.isdigit():
            print("Ongeldig ID.")
            return []
        cursor.execute("""
            SELECT id, date, counter_party_name, amount, direction, category_id
            FROM transactions
            WHERE id = ?
        """, (int(tx_id),))
    elif choice == "3":
        date = input("Datum (YYYY-MM-DD): ").strip()
        cursor.execute("""
            SELECT id, date, counter_party_name, amount, direction, category_id
            FROM transactions
            WHERE date = ?
            ORDER BY id
        """, (date,))
    else:
        print("Ongeldige keuze.")
        return []

    results = cursor.fetchall()
    if not results:
        print("Geen transacties gevonden.")
        return []

    print()
    for tx_id, date, counter_party_name, amount, direction, category_id in results:
        label = get_category_label(cursor, category_id) if category_id else "ONGECATEGORISEERD"
        cursor.execute("SELECT COUNT(*) FROM transaction_splits WHERE transaction_id = ?", (tx_id,))
        split_marker = " [GESPLITST]" if cursor.fetchone()[0] > 0 else ""
        print(f"[{tx_id}] {date}  {counter_party_name[:40]:<40}  "
              f"{format_amount_nl(amount)} ({direction})  ->  {label}{split_marker}")

    return results


def show_splits(cursor, transaction_id):
    cursor.execute("""
        SELECT ts.id, ts.amount, c.main_type, c.group_name, c.subcategory
        FROM transaction_splits ts
        JOIN categories c ON ts.category_id = c.id
        WHERE ts.transaction_id = ?
    """, (transaction_id,))
    return cursor.fetchall()


def choose_category(cursor, prompt="Nieuwe categorie"):
    cursor.execute("SELECT DISTINCT main_type, group_name FROM categories ORDER BY main_type, group_name")
    group_rows = cursor.fetchall()

    while True:
        print(f"\nGroepen ({prompt}):")
        for i, (main_type, group_name) in enumerate(group_rows, start=1):
            print(f"  [{i}] {main_type} / {group_name}")

        group_choice = input("Groep: ").strip()
        if not group_choice.isdigit() or not (1 <= int(group_choice) <= len(group_rows)):
            print(f"'{group_choice}' is geen geldige groep-keuze.")
            continue

        selected_main_type, selected_group = group_rows[int(group_choice) - 1]

        cursor.execute(
            "SELECT id, subcategory FROM categories WHERE main_type = ? AND group_name = ? ORDER BY subcategory",
            (selected_main_type, selected_group)
        )
        subcats = cursor.fetchall()
        valid_ids = {cat_id for cat_id, _ in subcats}

        print(f"\nSubcategorieën binnen {selected_main_type} / {selected_group}:")
        for cat_id, subcategory in subcats:
            print(f"  [{cat_id}] {subcategory}")
        print("  [B] Terug naar groepen")

        sub_choice = input("Subcategorie: ").strip()
        if sub_choice.upper() == "B":
            continue
        if not sub_choice.isdigit() or int(sub_choice) not in valid_ids:
            print(f"'{sub_choice}' is geen geldige subcategorie-ID.")
            continue

        return int(sub_choice)

def recategorize_simple(cursor, transaction_id):
    """Wijzig de categorie van een niet-gesplitste transactie."""
    new_category_id = choose_category(cursor)
    cursor.execute(
        "UPDATE transactions SET category_id = ?, rule_id = NULL WHERE id = ?",
        (new_category_id, transaction_id)
    )
    label = get_category_label(cursor, new_category_id)
    print(f"Bijgewerkt naar: {label} (koppeling met regel is verwijderd)")


def recategorize_splits(cursor, transaction_id, splits):
    """Wijzig de categorie van één of meer bestaande splits."""
    print("\nHuidige splits:")
    for split_id, amount, main_type, subcategory in splits:
        print(f"  [{split_id}] {format_amount_nl(amount)}  ->  {main_type} / {subcategory}")

    split_id_input = input("\nID van de split die je wilt wijzigen (of A voor allemaal opnieuw instellen): ").strip()

    if split_id_input.upper() == "A":
        for split_id, amount, _, _ in splits:
            print(f"\nSplit van {format_amount_nl(amount)}:")
            new_category_id = choose_category(cursor)
            cursor.execute("UPDATE transaction_splits SET category_id = ? WHERE id = ?", (new_category_id, split_id))
    elif split_id_input.isdigit():
        split_id = int(split_id_input)
        valid_split_ids = {s[0] for s in splits}
        if split_id not in valid_split_ids:
            print("Ongeldig split-ID.")
            return
        new_category_id = choose_category(cursor)
        cursor.execute("UPDATE transaction_splits SET category_id = ? WHERE id = ?", (new_category_id, split_id))
    else:
        print("Ongeldige keuze.")
        return

    # werk de hoofdcategorie van de transactie bij naar de grootste split
    cursor.execute("SELECT category_id, amount FROM transaction_splits WHERE transaction_id = ?", (transaction_id,))
    updated_splits = cursor.fetchall()
    largest_category_id = max(updated_splits, key=lambda s: s[1])[0]
    cursor.execute(
        "UPDATE transactions SET category_id = ?, rule_id = NULL WHERE id = ?",
        (largest_category_id, transaction_id)
    )
    print("Splits bijgewerkt.")


def recategorize(cursor):
    results = search_transactions(cursor)
    if not results:
        return

    tx_id_input = input("\nTransactie-ID om te wijzigen (leeg = annuleren): ").strip()
    if not tx_id_input:
        return
    if not tx_id_input.isdigit():
        print("Ongeldig ID.")
        return
    transaction_id = int(tx_id_input)

    valid_ids = {r[0] for r in results}
    if transaction_id not in valid_ids:
        print("Dat ID stond niet in de zoekresultaten.")
        return

    splits = show_splits(cursor, transaction_id)
    if splits:
        recategorize_splits(cursor, transaction_id, splits)
    else:
        recategorize_simple(cursor, transaction_id)


if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    while True:
        print("\n=== Transactie hercategoriseren ===")
        print("  [1] Zoek en wijzig een transactie")
        print("  [Q] Stoppen")
        choice = input("Keuze: ").strip().upper()

        if choice == "1":
            recategorize(cursor)
            conn.commit()
        elif choice == "Q":
            break

    conn.close()
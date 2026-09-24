import sqlite3
from db_helpers import DB_PATH, create_new_category


def list_categories(cursor):
    cursor.execute("SELECT id, main_type, group_name, subcategory FROM categories ORDER BY main_type, group_name, subcategory")
    categories = cursor.fetchall()
    for cat_id, main_type, group_name, subcategory in categories:
        print(f"  [{cat_id}] {main_type} / {group_name} / {subcategory}")
    return categories


def count_usages(cursor, category_id):
    """Count how many transactions and rules reference this category."""
    cursor.execute("SELECT COUNT(*) FROM transactions WHERE category_id = ?", (category_id,))
    tx_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM transaction_splits WHERE category_id = ?", (category_id,))
    split_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM rules WHERE category_id = ?", (category_id,))
    rule_count = cursor.fetchone()[0]

    return tx_count, split_count, rule_count


def edit_category(cursor):
    list_categories(cursor)
    cat_id_input = input("\nCategory ID to edit: ").strip()
    if not cat_id_input.isdigit():
        print("Invalid ID.")
        return
    cat_id = int(cat_id_input)

    cursor.execute("SELECT main_type, group_name, subcategory FROM categories WHERE id = ?", (cat_id,))
    result = cursor.fetchone()
    if result is None:
        print("Category not found.")
        return

    current_main_type, current_group_name, current_subcategory = result
    print(f"Current: {current_main_type} / {current_group_name} / {current_subcategory}")

    new_group_name = input(f"New group name [{current_group_name}]: ").strip()
    if not new_group_name:
        new_group_name = current_group_name

    new_subcategory = input(f"New subcategory name [{current_subcategory}]: ").strip()
    if not new_subcategory:
        new_subcategory = current_subcategory

    change_main = input(f"Change main_type from '{current_main_type}'? (y/n): ").strip().lower()
    new_main_type = current_main_type

    if change_main == "y":
        tx_count, split_count, rule_count = count_usages(cursor, cat_id)
        total_affected = tx_count + split_count + rule_count
        if total_affected > 0:
            print(f"\nWarning: this category is used by {tx_count} transaction(s), "
                  f"{split_count} split(s), and {rule_count} rule(s).")
            print("Changing main_type will retroactively reclassify all of them.")
            confirm = input("Are you sure you want to continue? (y/n): ").strip().lower()
            if confirm != "y":
                print("Cancelled.")
                return

        print("  [1] inkomen")
        print("  [2] uitgaven")
        print("  [3] transfer")
        type_choice = input("New main type: ").strip()
        type_map = {"1": "inkomen", "2": "uitgaven", "3": "transfer"}
        new_main_type = type_map.get(type_choice, current_main_type)

    try:
        cursor.execute(
            "UPDATE categories SET main_type = ?, group_name = ?, subcategory = ? WHERE id = ?",
            (new_main_type, new_group_name, new_subcategory, cat_id)
        )
        print(f"Updated to: {new_main_type} / {new_group_name} / {new_subcategory}")
    except sqlite3.IntegrityError:
        print(f"'{new_main_type} / {new_group_name} / {new_subcategory}' already exists as a different category. Cancelled.")

def delete_category(cursor):
    list_categories(cursor)
    cat_id_input = input("\nCategory ID to delete: ").strip()
    if not cat_id_input.isdigit():
        print("Invalid ID.")
        return
    cat_id = int(cat_id_input)

    tx_count, split_count, rule_count = count_usages(cursor, cat_id)
    if tx_count + split_count + rule_count > 0:
        print(f"\nCannot delete: this category is used by {tx_count} transaction(s), "
              f"{split_count} split(s), and {rule_count} rule(s).")
        print("Reassign or delete those first.")
        return

    confirm = input("Are you sure you want to delete this category? (y/n): ").strip().lower()
    if confirm == "y":
        cursor.execute("DELETE FROM categories WHERE id = ?", (cat_id,))
        print("Deleted.")
    else:
        print("Cancelled.")


if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    while True:
        print("\n=== Category manager ===")
        print("  [1] List all categories")
        print("  [2] Add a new category")
        print("  [3] Edit a category")
        print("  [4] Delete a category")
        print("  [Q] Quit")
        choice = input("Choice: ").strip().upper()

        if choice == "1":
            list_categories(cursor)
        elif choice == "2":
            create_new_category(cursor)
            conn.commit()
        elif choice == "3":
            edit_category(cursor)
            conn.commit()
        elif choice == "4":
            delete_category(cursor)
            conn.commit()
        elif choice == "Q":
            break

    conn.close()
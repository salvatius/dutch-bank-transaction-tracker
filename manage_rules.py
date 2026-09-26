import sqlite3
from db_helpers import DB_PATH, describe_rule


def list_rules(cursor):
    cursor.execute("""
        SELECT rules.id, rules.priority, categories.main_type, categories.subcategory
        FROM rules
        JOIN categories ON rules.category_id = categories.id
        ORDER BY rules.priority DESC, rules.id ASC
    """)
    rules = cursor.fetchall()

    dead_ids = find_dead_rules(cursor)

    for rule_id, priority, main_type, subcategory in rules:
        cond_text = describe_rule(cursor, rule_id)
        flag = "  [DEAD - unreachable]" if rule_id in dead_ids else ""
        print(f"[{rule_id}] priority={priority}  ->  {main_type}/{subcategory}   ({cond_text}){flag}")

    return rules


def get_conditions(cursor, rule_id):
    cursor.execute(
        "SELECT field, match_type, value, value2 FROM rule_conditions WHERE rule_id = ?",
        (rule_id,)
    )
    return cursor.fetchall()


def find_dead_rules(cursor):
    """A rule is flagged dead if an earlier-checked rule's conditions are a
    subset of its own (same field/match_type/value pairs) - meaning the
    earlier rule matches everything this one would, and runs first."""
    cursor.execute("SELECT id, priority FROM rules ORDER BY priority DESC, id ASC")
    ordered_rules = cursor.fetchall()

    dead_ids = set()
    seen_condition_sets = []  # list of (rule_id, frozenset of conditions)

    for rule_id, _ in ordered_rules:
        conditions = set(get_conditions(cursor, rule_id))

        for earlier_rule_id, earlier_conditions in seen_condition_sets:
            if earlier_conditions.issubset(conditions):
                dead_ids.add(rule_id)
                break

        seen_condition_sets.append((rule_id, conditions))

    return dead_ids


def set_priority(cursor, rule_id, new_priority):
    cursor.execute("UPDATE rules SET priority = ? WHERE id = ?", (new_priority, rule_id))


def delete_rule(cursor):
    list_rules(cursor)
    rule_id_input = input("\nRule ID to delete: ").strip()
    if not rule_id_input.isdigit():
        print("Invalid ID.")
        return
    rule_id = int(rule_id_input)

    cursor.execute("SELECT id FROM rules WHERE id = ?", (rule_id,))
    if cursor.fetchone() is None:
        print("Rule not found.")
        return

    cursor.execute("SELECT COUNT(*) FROM transactions WHERE rule_id = ?", (rule_id,))
    tx_count = cursor.fetchone()[0]

    if tx_count > 0:
        print(f"\n{tx_count} transaction(s) were auto-categorized by this rule.")
        print("They will keep their current category, but lose the link to this rule.")

    confirm = input("Delete this rule and all its conditions? (y/n): ").strip().lower()
    if confirm != "y":
        print("Cancelled.")
        return

    cursor.execute("UPDATE transactions SET rule_id = NULL WHERE rule_id = ?", (rule_id,))
    cursor.execute("DELETE FROM rule_conditions WHERE rule_id = ?", (rule_id,))
    cursor.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
    print("Deleted.")


def edit_rule_conditions(cursor):
    list_rules(cursor)
    rule_id_input = input("\nRule ID to edit conditions for: ").strip()
    if not rule_id_input.isdigit():
        print("Invalid ID.")
        return
    rule_id = int(rule_id_input)

    cursor.execute("SELECT id FROM rules WHERE id = ?", (rule_id,))
    if cursor.fetchone() is None:
        print("Rule not found.")
        return

    print(f"Current conditions: {describe_rule(cursor, rule_id)}")
    print("This will replace ALL conditions on this rule.")
    confirm = input("Continue? (y/n): ").strip().lower()
    if confirm != "y":
        print("Cancelled.")
        return

    new_conditions = []
    while True:
        print("\nAdd a condition. Match on which field?")
        print("  [1] counter_party_name / tegenrekeninghouder")
        print("  [2] notes")
        print("  [3] counter_account")
        print("  [4] own_account")
        print("  [5] amount")
        print("  [6] direction")
        field_choice = input("Choice: ").strip()
        field_map = {
            "1": "counter_party_name", "2": "notes", "3": "counter_account",
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
            value = input("Amount value: ").strip()
            value2 = input("Upper bound: ").strip() if match_type == "between" else None

        elif field == "direction":
            print("Match value? [1] debit  [2] credit")
            dir_choice = input("Choice: ").strip()
            value = "debit" if dir_choice == "1" else "credit"
            match_type = "exact"
            value2 = None

        else:
            value = input("Value to match (contains): ").strip()
            match_type = "contains"
            value2 = None

        new_conditions.append((field, match_type, value, value2))

        more = input("Add another condition? (y/n): ").strip().lower()
        if more != "y":
            break

    cursor.execute("DELETE FROM rule_conditions WHERE rule_id = ?", (rule_id,))
    for field, match_type, value, value2 in new_conditions:
        cursor.execute(
            "INSERT INTO rule_conditions (rule_id, field, match_type, value, value2) VALUES (?, ?, ?, ?, ?)",
            (rule_id, field, match_type, value, value2)
        )
    print("Conditions updated.")


if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    while True:
        print("\n=== Rule manager ===")
        print("  [1] List all rules (dead rules flagged)")
        print("  [2] Change a rule's priority")
        print("  [3] Edit a rule's conditions")
        print("  [4] Delete a rule")
        print("  [Q] Quit")
        choice = input("Choice: ").strip().upper()

        if choice == "1":
            list_rules(cursor)
        elif choice == "2":
            rule_id = input("Rule ID: ").strip()
            new_priority = input("New priority (higher = checked first): ").strip()
            if rule_id.isdigit() and new_priority.lstrip("-").isdigit():
                set_priority(cursor, int(rule_id), int(new_priority))
                conn.commit()
                print("Updated.")
            else:
                print("Invalid input.")
        elif choice == "3":
            edit_rule_conditions(cursor)
            conn.commit()
        elif choice == "4":
            delete_rule(cursor)
            conn.commit()
        elif choice == "Q":
            break

    conn.close()
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "finance.db"


def list_rules(cursor):
    cursor.execute("""
        SELECT rules.id, rules.priority, categories.main_type, categories.subcategory
        FROM rules
        JOIN categories ON rules.category_id = categories.id
        ORDER BY rules.priority DESC, rules.id ASC
    """)
    rules = cursor.fetchall()

    for rule_id, priority, main_type, subcategory in rules:
        cursor.execute(
            "SELECT field, match_type, value, value2 FROM rule_conditions WHERE rule_id = ?",
            (rule_id,)
        )
        conditions = cursor.fetchall()
        cond_text = " AND ".join(
            f"{f} {m} {v}" + (f"-{v2}" if v2 else "")
            for f, m, v, v2 in conditions
        )
        print(f"[{rule_id}] priority={priority}  ->  {main_type}/{subcategory}   ({cond_text})")


def set_priority(cursor, rule_id, new_priority):
    cursor.execute("UPDATE rules SET priority = ? WHERE id = ?", (new_priority, rule_id))


if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    while True:
        print("\n=== Rule manager ===")
        print("  [1] List all rules")
        print("  [2] Change a rule's priority")
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
        elif choice == "Q":
            break

    conn.close()
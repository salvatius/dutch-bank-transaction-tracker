import sqlite3
from db_helpers import (
    DB_PATH, load_known_accounts, get_opening_balance,
    set_opening_balance, calculate_balance, format_amount_nl
)


def list_accounts(cursor):
    known_accounts = load_known_accounts()
    if not known_accounts:
        print("Geen bekende rekeningen gevonden in known_accounts.json.")
        return

    for account_number, schema_file in known_accounts.items():
        opening = get_opening_balance(cursor, account_number)
        if opening:
            opening_date, opening_balance = opening
            current = calculate_balance(cursor, account_number)
            print(f"{account_number} ({schema_file})")
            print(f"    Openingssaldo: {format_amount_nl(opening_balance)} op {opening_date}")
            print(f"    Huidig saldo:  {format_amount_nl(current)}")
        else:
            print(f"{account_number} ({schema_file}) - geen openingssaldo ingesteld")

def set_balance_interactive(cursor):
    known_accounts = load_known_accounts()
    print("\nBekende rekeningen:")
    for account_number in known_accounts:
        print(f"  {account_number}")

    account_number = input("\nRekeningnummer: ").strip()
    opening_date = input("Datum van dit saldo (YYYY-MM-DD): ").strip()
    balance_input = input("Saldo op die datum: ").strip()

    try:
        opening_balance = float(balance_input.replace(",", "."))
    except ValueError:
        print("Ongeldig bedrag.")
        return

    set_opening_balance(cursor, account_number, opening_date, opening_balance)
    print(f"Opgeslagen: {account_number} = {format_amount_nl(opening_balance)} op {opening_date}")


def show_balance_as_of(cursor):
    account_number = input("Rekeningnummer: ").strip()
    date_input = input("Saldo per welke datum? (YYYY-MM-DD, leeg = meest recent): ").strip()
    as_of_date = date_input if date_input else None

    balance = calculate_balance(cursor, account_number, as_of_date)
    if balance is None:
        print("Geen openingssaldo bekend voor deze rekening.")
    else:
        label = as_of_date if as_of_date else "meest recente bekende datum"
        print(f"Saldo op {label}: {format_amount_nl(balance)}")


if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    while True:
        print("\n=== Rekeningbeheer ===")
        print("  [1] Toon alle rekeningen met openingssaldo en huidig saldo")
        print("  [2] Openingssaldo instellen/bijwerken")
        print("  [3] Saldo op specifieke datum opvragen")
        print("  [Q] Stoppen")
        choice = input("Keuze: ").strip().upper()

        if choice == "1":
            list_accounts(cursor)
        elif choice == "2":
            set_balance_interactive(cursor)
            conn.commit()
        elif choice == "3":
            show_balance_as_of(cursor)
        elif choice == "Q":
            break

    conn.close()
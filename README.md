# Dutch Bank Transaction Tracker

A Python tool for importing, deduplicating, and categorizing personal bank transactions from Dutch bank CSV exports (currently ING; Knab and SNS/ASN planned) — stored locally in SQLite, with an interactive CLI workflow for assigning categories, a rules engine that learns and auto-applies past categorizations, and CSV/Excel export for manual review.

Built as a learning project to go deeper with Python, while solving a real problem: getting a clear, private, self-hosted view of personal spending across multiple banks without uploading bank data to a third-party app.

## Features

- **Multi-bank CSV import** — each bank's CSV format and column layout is defined in a schema file (`schemas/*.json`); transactions are translated into one consistent internal format regardless of source
- **Multi-file scanning** — drop one or more bank export CSVs into `imports/`; the importer picks up every new file automatically and marks each as processed (`.imported`) so re-running never double-imports
- **Duplicate detection** — SHA-256 hashing of transaction records prevents re-importing the same transaction twice, even across overlapping export files
- **Rules engine** — categorize a transaction once, optionally save it as a rule, and future matching transactions are categorized automatically. Rules can match on description, notes, counter account, own account, amount (exact/greater-than/less-than/between), and direction (debit/credit), combined with AND logic, with priority ordering to resolve conflicts between overlapping rules
- **Auto-accept mode** (`--auto-accept`) — skip per-transaction confirmation for rule-matched rows once you trust your ruleset; unmatched transactions still prompt as normal
- **Transaction splitting** — allocate a single transaction across multiple categories (e.g. one payment covering two budget categories), with validation that split amounts sum exactly to the transaction total
- **Category management** — add, rename, reclassify, or delete categories via CLI, with safeguards against deleting categories still in use
- **Rule management** — list, reprioritize, edit, or delete rules, including detection of "dead" rules that can never fire because a broader, higher-priority rule already matches everything they would
- **CSV & Excel export** — export transactions (optionally filtered by date range, category, or uncategorized-only) to a Dutch-formatted CSV or a formatted `.xlsx` file with dropdown data validation on the category columns
- **Local SQLite storage** — all data stays on your machine, no cloud service involved
- **Rekeningsaldo-tracking** — leg een openingssaldo per rekening vast (bedrag + datum), waarna het lopend saldo op elke gewenste datum automatisch wordt berekend uit dat ijkpunt plus alle geïmporteerde mutaties — werkt ook met terugwerkende kracht als je oudere jaren later importeert
- **Rekeningbeheer** (`manage_accounts.py`) — openingssaldi instellen/bijwerken en huidig of historisch saldo per rekening opvragen

## Why this exists

Most budgeting tools either want you to link your bank accounts to a third party, or are locked into a single bank's export format. This project keeps everything local, is designed to support multiple Dutch banks side by side, and gives full control over how transactions are parsed, deduplicated, and categorized — while being a practical way to learn Python fundamentals (file I/O, hashing, SQLite, CLI design, module design) on a real, personal dataset.

## Supported banks

| Bank | Status |
|---|---|
| ING | Supported |
| Knab | Supported |
| SNS / ASN | Supported |

## Tech stack

- Python 3.x
- SQLite (via the `sqlite3` standard library)
- `hashlib` for duplicate detection
- `openpyxl` for Excel export

## Getting started

```bash
git clone https://github.com/salvatius/dutch-bank-transaction-tracker.git
cd dutch-bank-transaction-tracker
python -m venv venv
venv\Scripts\activate      # Windows
pip install -r requirements.txt
```

Initialize the database (creates all tables, and optionally seeds starter categories):
```bash
python init_db.py
```

If a `categories_starter.csv` file (semicolon-separated, columns `main_type;subcategory`) exists in the project root, its contents are offered as starter categories. Otherwise a small built-in example set is offered instead. Either can be skipped — categories can always be added later via `manage_categories.py`.


Copy `known_accounts.example.json` to `known_accounts.json` and add your own bank accounts

## Usage

### Import transactions

Place one or more bank export CSVs into `imports/`, then run:

```bash
python import.py
```

Every new file is processed once; already-imported files (renamed with a `.imported` suffix) are skipped on future runs. You'll be prompted to categorize any transaction that doesn't match an existing rule, with the option to save your choice as a new rule.

Skip confirmation for rule-matched transactions:

```bash
python import.py --auto-accept
```

### Export transactions

To CSV (Dutch comma-decimal formatting):

```bash
python export.py
python export.py --from 2026-01-01 --to 2026-01-31
python export.py --category "uitgaven/boodschappen"
python export.py --uncategorized
```

To Excel, with dropdown-validated category columns:

To Excel, with dropdown-validated category columns:

```bash
python export_excel.py
python export_excel.py --account <account number>
```

(Same `--from`, `--to`, `--category`, `--uncategorized`, and `--account` filters apply. The sheet also shows the applied filters and the start/end balance for the period, per account.)

Exports are written to `exports/`, timestamped, never overwritten.
- **CSV & Excel export** — export transactions (optionally filtered by date range, category, account, or uncategorized-only) to a Dutch-formatted CSV or a formatted `.xlsx` file with dropdown data validation on the category columns; the Excel export also shows the active filters and the start/end balance for the exported period (per account) at the top of the sheet

### Manage categories

```bash
python manage_categories.py
```

List, add, rename, reclassify, or delete categories.

### Manage rules

```bash
python manage_rules.py
```

List rules (with dead/unreachable rules flagged), change priority, edit conditions, or delete a rule.

### Manage accounts

```bash
python manage_accounts.py
```

Set or update an account's opening balance (amount + date), view current balances for all known accounts, or look up a balance as of a specific date.

### Recategorize an existing transaction

```bash
python recategorize.py
```

Search for an already-imported transaction (by description, transaction ID, or date), and correct its category. Works for both regular and split transactions — for a split transaction you can update one specific split or redo the whole split's categorization. Manually recategorizing always clears the transaction's link to whichever rule originally categorized it, since that link no longer reflects how the category was actually assigned.

## Project status

🚧 Actively in development. Current focus: a desktop GUI (tkinter) for reviewing and correcting categorized transactions.

## Privacy note

This tool is designed to run entirely locally. Your CSV exports and database are excluded from version control via `.gitignore` — never commit real transaction data to this repository.

## License

MIT
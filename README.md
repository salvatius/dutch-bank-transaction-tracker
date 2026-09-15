# Dutch Bank Transaction Tracker

A Python tool for importing, deduplicating, and categorizing personal bank transactions from Dutch bank CSV exports (currently ING, Knab, and SNS/ASN) — stored locally in SQLite, with an interactive CLI workflow for assigning categories.

Built as a learning project to go deeper with Python, while solving a real problem: getting a clear, private, self-hosted view of personal spending across multiple banks without uploading bank data to a third-party app.

## Features

- **Multi-bank CSV import** — each bank has its own parser (ING, Knab, SNS/ASN) behind a common interface, so all transactions land in one consistent format regardless of source
- **Duplicate detection** — SHA-256 hashing of transaction records prevents re-importing the same transaction twice, even across overlapping export files or banks
- **Local SQLite storage** — all data stays on your machine, no cloud service involved
- **Interactive categorization** — CLI workflow to assign categories to new transactions as they come in

## Why this exists

Most budgeting tools either want you to link your bank accounts to a third party, or are locked into a single bank's export format. This project keeps everything local, supports multiple Dutch banks side by side, and gives full control over how transactions are parsed, deduplicated, and categorized — while being a practical way to learn Python fundamentals (file I/O, hashing, SQLite, CLI design, module design) on a real, multi-source dataset.

## Supported banks

| Bank | Status |
|---|---|
| ING | Supported |
| Knab | Not yet supported |
| SNS / ASN | Not yet supported |

## Tech stack

- Python 3.x
- SQLite (via `sqlite3` standard library)
- `hashlib` for duplicate detection

## Getting started

```bash
git clone https://github.com/yourname/dutch-bank-transaction-tracker.git
cd dutch-bank-transaction-tracker
python -m venv venv
venv\Scripts\activate      # Windows
pip install -r requirements.txt
```

## Usage

```bash
python import.py
```

You'll be prompted to categorize any new, uncategorized transactions.

## Project status

🚧 Actively in development. Current focus: [extending rule creation possibilities / categorization workflow].

## Privacy note

This tool is designed to run entirely locally. Your CSV exports and database are excluded from version control via `.gitignore` — never commit real transaction data to this repository.

## License

MIT

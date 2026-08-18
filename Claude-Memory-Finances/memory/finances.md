# Finances — Auto-Logging System

## The Database
- **Name:** 💰 Financial Tracker
- **URL:** https://app.notion.com/p/8523b07eb34849e48fee1688953623a1
- **Data source ID (for Notion MCP create/update):** `3dda757b-c875-4d99-9928-b854c5396c75`
- **Query table name (for SQL):** `collection://3dda757b-c875-4d99-9928-b854c5396c75`

## When to log
Create a new row whenever Aryan, in ANY chat:
- says he bought / purchased / paid for / spent on something
- sends or uploads a receipt (image, PDF, screenshot, forwarded email)
- mentions income / a refund / reimbursement (use Category "Income", positive Amount)

Log **automatically** (no confirmation). Afterward reply with one line: item, amount, category, and the Notion link.

## How to log (tool: notion-create-pages)
- `parent`: `{ "data_source_id": "3dda757b-c875-4d99-9928-b854c5396c75" }`
- `properties`:
  - `"Item"` — short name of what was bought (this is the title)
  - `"date:Date:start"` — purchase date, ISO `YYYY-MM-DD`. Default to **today** if not stated.
  - `"Amount"` — dollar amount as a plain number (no `$`)
  - `"Category"` — one of the allowed values below (best guess)
  - `"Payment Method"` — one of the allowed values if known, else blank
  - `"Merchant"` — store/vendor name if known
  - `"Recurring"` — `"__YES__"` for subscriptions/recurring charges, else `"__NO__"`
  - `"Notes"` — anything extra (receipt line items, context)
  - `"Receipt"` — attach a file if a receipt URL is available (see Receipts)
- Do NOT set `Month`, `Txn ID`, or `Added` — they are automatic.

## Allowed Category values
Food & Dining, Groceries, Transportation, Housing & Rent, Utilities, Subscriptions, Education, Health & Medical, Shopping, Entertainment, Personal Care, Travel, Fees & Charges, Income, Other

## Allowed Payment Method values
Credit Card, Debit Card, Cash, Venmo, Apple Pay, PayPal, Zelle, Bank Transfer, Other

## Category quick-guesses
- coffee, restaurant, takeout, snacks → **Food & Dining**
- supermarket, grocery run → **Groceries**
- gas, Uber/Lyft, bus, parking → **Transportation**
- rent, deposit → **Housing & Rent**
- phone, internet, electric, water → **Utilities**
- Netflix/Spotify/ChatGPT/gym/any monthly plan → **Subscriptions** (set Recurring = yes)
- textbooks, tuition, course/lab fees → **Education**
- pharmacy, doctor, copay, prescriptions → **Health & Medical**
- clothes, electronics, household, general Amazon → **Shopping**
- movies, games, concerts, events → **Entertainment**
- haircut, skincare, toiletries → **Personal Care**
- flights, hotels, trips → **Travel**
- bank/late fee, interest → **Fees & Charges**
- paycheck, refund, reimbursement, Venmo received → **Income**

## Receipts (images / PDFs)
1. Read the receipt; extract merchant, date, total, and notable line items.
2. Create the row from those details (put line items in Notes if useful).
3. Files attach by URL. If the receipt is only a local upload (no public URL), log the parsed data and write "(receipt on file)" in Notes, and tell Aryan the image itself wasn't attached.
4. One receipt = one row for the total by default, unless Aryan asks to split line items.

## Reports / queries
NOTE: the SQL `notion-query-data-sources` tool requires a Notion Enterprise plan with AI, which this account does NOT have — don't use it (returns a 400 upsell error).
Instead:
- Read rows with `notion-fetch` on the database URL or `collection://3dda757b-c875-4d99-9928-b854c5396c75`, then total/group them yourself (or with a quick script).
- For always-on totals in Notion's own UI: open the database, add a Table view grouped by **Category** (or **Month**), and turn on **Calculate → Sum** on the Amount column. These update automatically — no tool needed.

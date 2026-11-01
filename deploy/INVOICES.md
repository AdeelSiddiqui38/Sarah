# Remedy Pills invoice pipeline (Sarah)

**Mailbox:** remedypillspharmacy@gmail.com (read-only IMAP, Google app password in Sarah's vault, never in files)
**Folder:** `S:\Remedy Pills\Finance\Invoices` (container path `/invoices`, env `SARAH_INVOICE_DIR`)

| Vendor | Cadence | Folder | Notes |
|---|---|---|---|
| Nayel Anwer (nayelanwer@gmail.com) | Weekly | `Pharmacist - Nayel Anwer` | Only files with "invoice" in the name; 46 backfilled (Dec 29 2025 - Oct 31 2026) |
| Kharb (info@kharb.ca) | Monthly | `Kharb` | Monthly check starts Dec 2026: 3rd, retry 10th, then "Missing" draft |
| Pharma Planet Labs, Pharmaris, fordbi (Shaw), Sharath Velagandula, a.sid38 (Hotmail) | One-time | `One-time\<name>` | Occasional purchases |

**Rules**
- Tuesday: Sarah fetches new invoices for all vendors (also button: Settings > Fetch invoices now).
- Unknown sender with invoice/statement/bill subject + attachment: parked in `_Inbox\<sender>` + draft "New invoice sender(s) to review".
- Identical files are skipped; strays go to `_Other`, copies to `_Duplicates`. Nothing is deleted. Nothing is paid or sent.
- Vendor list lives in `DEFAULT_VENDORS` in sarah_core.py (tell Claude to add/change vendors).

**Not built yet:** missing-week check for Nayel, missing-month check beyond Kharb, vendor edit screen.
**Setup done:** TrueNAS YAML has `SARAH_INVOICE_DIR` + Invoices volume; Chrome download location was temporarily set to the Nayel folder (switch back to Downloads).

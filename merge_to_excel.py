"""Fold the ledger rows Adeel approved in Sarah into the APEX Cost Controller workbook (run on the PC, needs openpyxl).

    python merge_to_excel.py "S:\\APEX Physio\\Finance"            # does it
    python merge_to_excel.py "S:\\APEX Physio\\Finance" --dry-run   # shows what would be added

Close the workbook in Excel first. A copy of the workbook is saved to Finance\\_backup before anything is written.
Only the data columns are filled; the Month / Each Partner / Cash Effect formulas are already in the sheet down to row 400."""
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

import openpyxl

WB = "APEX_PHYSIO_Cost_Controller.xlsx"
COLS = {"account": 3, "type": 4, "category": 5, "desc": 6, "in": 7, "out": 8, "shared": 9, "paid_by": 11, "status": 12, "notes": 13}


def merge(finance, dry=False):
    finance = Path(finance)
    adds_path = finance / "Sarah Data" / "apex-ledger-adds.json"
    adds = json.loads(adds_path.read_text(encoding="utf-8")) if adds_path.is_file() else {"rows": []}
    todo = [r for r in adds["rows"] if not r.get("merged")]
    if not todo:
        return 0
    path = finance / WB
    wb = openpyxl.load_workbook(path)
    ws = wb["Ledger"]
    row = 4
    for r in range(4, 505):      # first row after the last one that holds data (some earlier rows have no date)
        if any(ws.cell(r, c).value not in (None, "") for c in (1, 3, 4, 5, 6, 7, 8)):
            row = r + 1
    if row + len(todo) > 504:
        raise SystemExit("Ledger is full (row 504). Extend the sheet first.")
    for r in todo:
        print(f"row {row}: {r['date']}  {r['account']}  {r['type']}  {r['category']}  in {r.get('in') or ''}  out {r.get('out') or ''}  {r['desc'][:50]}")
        if not dry:
            ws.cell(row, 1).value = dt.datetime.fromisoformat(r["date"])
            ws.cell(row, 1).number_format = "YYYY-MM-DD"
            for k, c in COLS.items():
                v = r.get(k)
                if k in ("in", "out"):
                    v = float(v) if v else None
                ws.cell(row, c).value = v if v not in ("", 0, 0.0) else None
            r["merged"] = dt.date.today().isoformat()
        row += 1
    if dry:
        return len(todo)
    backup = finance / "_backup"
    backup.mkdir(exist_ok=True)
    shutil.copy2(path, backup / f"APEX_PHYSIO_Cost_Controller_{dt.datetime.now():%Y-%m-%d_%H%M}_before-merge.xlsx")
    wb.save(path)
    adds_path.write_text(json.dumps(adds, indent=1, ensure_ascii=False), encoding="utf-8")
    return len(todo)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    n = merge(sys.argv[1], "--dry-run" in sys.argv)
    print(f"{n} row(s) {'would be ' if '--dry-run' in sys.argv else ''}added.")

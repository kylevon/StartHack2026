# Soony data explorer

A local, dependency-free view of the whole Soony portal snapshot: launch status, rule-based findings, parts and stock, pack-out, shipments, POs, goods receipts, suppliers and every document (scans, PDFs with extracted text, spreadsheets).

```bash
cd asklio
python3 explorer/build.py --serve     # builds explorer/data.json, serves http://localhost:8000/explorer/
```

- Input: `data/soony-data/` (unzipped automatically from `data/soony-data.zip` if missing). After a new drop, replace the zip/folder and re-run the build.
- Needs Python 3.10+ and, for PDF text, `pdftotext` (poppler). No pip packages.
- `data.json` contains customer data and is gitignored.
- Findings are generic rules in `build.py` (over-booked receipts, rejected inspections still in stock, receipts without PO, shortages vs. bill of materials, shipments arriving after launch, tracker vs ERP, order confirmation vs PO, expired conditional releases). Nothing is hardcoded to specific parts or suppliers.

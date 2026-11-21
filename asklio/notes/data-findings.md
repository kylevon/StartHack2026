# Data findings: first review (Sat 21 Nov)

Source: portal snapshot of 2026-11-20. The data is not in git; `scripts/update_data.py --apply` checks out the current snapshot into `data/soony-data/`.

> Newer snapshots are reviewed in `data/CHANGELOG.md`. The 21 Nov drop changes findings 1 (art books) and 3 (game cards) and adds a sleeve revision problem.

**Headline:** the launch plan marks every part "ok" except the lid magnets. In reality the magnets are fine, and **art books and statues are short**, which caps the Collector's Edition at about **19,300 of the 25,200** still to pack.

## Basics
- Remaining: Standard 128,000, Collector's (CE) 25,200. Pre-orders: 415k Standard + 72k CE = 487k.
- Shifts: Sat 06:00–22:00, Sun 06:00–20:00 (30 h). Planned rates: Standard 6,000/h (needs 21.3 h), CE 900/h (needs 28 of 30 h).
- The ERP is internally consistent: stock = goods received − units packed. The errors are in what receiving booked.

## Findings, by impact

### 1. Art books: system 91,300, reality about 19,300 (about 5,900 short)
- Goods receipt `5000413065` (PO 4500318768/3): ordered 8,000, booked **80,000**, "over delivery accepted".
- Scan `receiving/DC-HAM/20261118_WZ-261116-473.jpg`: printed 80,000 is crossed out, **8 000 handwritten**.
- Karton Nowak (only art-book source) notice `Zawiadomienie_przestoj_techniczny_2026-11.pdf`: bindery and offset press down **Sat 21.11 14:00 – Mon 23.11 06:00**. Shipping finished goods from their warehouse is still possible. The express offset deadline was Sat 09:00. Poznań to Hamburg is a 1-day truck (RT-010).

### 2. Statues: 27,400 in stock, but 5,600 failed inspection (3,400 short)
- `inspection_report_5000413063.pdf`: Pune lot, AQL 1.0, 9 of 125 defective (accept 3 / reject 4). Booked as unrestricted anyway.
- Usable only under a concession from Supplier Quality (Daniel Okafor) **and the Collector's Items Category Lead, a vacant role** (org chart: TBD).
- Pune is "conditional" since 2026-08-01. PP-07 §5 limits conditional releases to 90 days, so it expired around 30 Oct. POs 4500318784 and 4500318791 are `awaiting_approval`.

### 3. Game cards: covered only if one air shipment arrives
- Need 153,200, stock 118,400 (34,800 short).
- Planned fix: 48,000 by air, Hwaseong SHP-2026-04311 (ICN→FRA, ETA FRA Sat 21, still "booked" at origin on Fri 12:00), plus a 1-day truck, so it arrives Sunday at best.
- Boise 36,000 (SHP-2026-04314, ETA 23 Nov) arrives after launch.

### 4. Game cases: 96,000 in stock vs 128,000 needed
- 350,000 cases (SHP-2026-04276) at CTA Hamburg: ERP says "available for pick-up", tracker says "in transit – RP: call terminal".
- Needs a truck plus a dock slot released by the site lead Katrin Jansen (PP-07 §3).

### 5. Magnets: false alarm
- The bill of materials says 4 magnets per CE, so the plan flags 100,800 missing.
- PackRight components file: magnets are fitted into the box by the supplier and not ordered, received or stocked separately. The bill of materials is wrong.

### 6. Other
- 78,000 `PRM-GH6-PIN` from Dongguan in 3 receipts with no PO, booked as "misc merchandise". Pre-order bonus?
- The tracker (`open_shipments_tracker_v37_FINAL_final2.xlsx`) is stale and missing about 10 shipments that are in `erp/open_shipments.csv`.
- Price creep through notices (Boise +4 % and +3 %, Dongguan +3 % twice, PackRight +4 %).

## Not reviewed yet
- Contracts are image-only scanned PDFs and need OCR.
- About 200 order confirmations and about 60 delivery-note scans: only 2 checked so far. Systematically comparing scans against goods receipts is the next step.

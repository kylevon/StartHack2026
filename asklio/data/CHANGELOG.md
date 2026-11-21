# Soony data changelog

One entry per portal snapshot, newest first. The data itself is not in git: get it with `python3 scripts/update_data.py --apply` (see `README.md` here).

<!-- new entries go below this line -->

## 2026-11-21 22:26 snapshot

Snapshot `cde498bb9627acef`, 332 files (19 added since the 16:09 snapshot, 0 changed, 0 removed).

The sync script reported "332 added, 303 removed" on this machine. That was the local folder still holding Friday's snapshot one directory too deep (`soony-data/soony-data/`), not a change at the portal. The list below is the real difference to the 16:09 snapshot.

### Added
- `soony/erp/stock_update_2026-11-21.xlsx`
- `soony/erp/goods_receipts_update.csv`
- `soony/news/2026-11-21_export_controls.json`
- `soony/receiving/DC-HAM/20261121_DN-261119-197.jpg`
- `soony/receiving/DC-HAM/20261121_DN-261120-726.jpg`
- `soony/receiving/DC-HAM/20261121_WZ-261120-732.jpg`
- `soony/receiving/DC-HAM/20260903_DN-260831-382.jpg`
- `soony/receiving/DC-HAM/20260903_WZ-260902-594.jpg`
- `soony/receiving/DC-HAM/20260904_SN-260730-216.jpg`
- `soony/receiving/DC-HAM/20260914_SN-260810-719.png`
- `soony/receiving/DC-HAM/20261009_WZ-261007-399.png`
- `soony/receiving/DC-HAM/20261106_DN-261102-986.jpg`
- `soony/receiving/DC-HAM/20261110_SN-261007-130.jpg`
- `soony/receiving/DC-HAM/20261111_DN-261106-613.png`
- `soony/receiving/DC-HAM/20261113_WZ-261110-805.jpg`
- `suppliers/SUP-0018_Pune_Diecast_Works/profile.json`
- `suppliers/SUP-0029_Guangzhou_PackRight/profile.json`
- `suppliers/SUP-0029_Guangzhou_PackRight/components_delta.csv`
- `suppliers/SUP-0029_Guangzhou_PackRight/notices/Supply_notice_export_licence_2026-11-21.pdf`

### What it means
Read on Sat 21 Nov, 22:30. Stock figures are book stock, not counted.

**Where the pack-out stands** (`stock_update_2026-11-21.xlsx`, Sat 20:50): Standard 602,000 packed, 38,000 to go. Collector's 60,300 packed, 11,700 to go. Saturday packed 90,000 Standard and 13,500 Collector's, so both ran at plan rate all day. Sunday has 14 hours: room for 84,000 Standard and 12,600 Collector's, so time is not the limit. Parts are.

**Book stock still carries the known errors.** Corrected for them:
- Art books: 77,800 on the books, 5,800 real (the 72,000 that never arrived are still in). Against 11,700: 5,900 short. At 900 an hour the cell runs out of art books around Sunday 11:15.
- Statues: 13,900 on the books, 8,300 good (the failed lot of 5,600 is still in). 3,400 short; they run out around Sunday 14:45.
- Game card cases: 6,000 left. Standard stops for want of cases before Saturday's shift ends. The 350,000 at the Hamburg terminal are still not collected.
- Game cards: 42,900 after the air receipt. Collector's takes 11,700 first (CPO memo), which leaves 31,200 for 38,000 Standard: 6,800 short.
- Sleeves: 116,000 on the books. That includes the 64,000 rev B batch and the 4,000 Grand Heist 5 sleeves below, so about 48,000 rev C if Saturday packed only rev C. To confirm at the DC.

**Receipts of today** (`goods_receipts_update.csv`):
- Hwaseong: 28,000 of 48,000 game cards received, the balance per shipping advice (24 Nov).
- Karton Nowak: 20,000 sleeves booked, but one pallet labelled GH6 holds 4,000 Grand Heist 5 sleeves (CMP-GAM-005). Only 16,000 rev C arrived; the booking overstates GH6 sleeves by 4,000.
- Boise: 10,500 Grand Heist 5 cards. No use for the launch.

**Rare-earth magnets: a problem for after the launch.** China now requires export licences for sintered NdFeB magnets (`2026-11-21_export_controls.json`). PackRight's magnet supplier has stopped shipping (`Supply_notice_export_licence`); Collector's boxes with delivery after 1 Dec move out six weeks, and `components_delta.csv` raises the box lead time from 63 to 105 days with no second source for the magnet. Boxes confirmed for November are covered. PackRight is now flagged "at risk" in the vendor master (`profile.json`) and offers ferrite or ribbon closures to sample within 10 days.

**Pune's qualification has lapsed** (`SUP-0018 profile.json`): conditional release valid until 2026-10-30, not extended, status "watch". The failed statue lot came from a supplier with no valid release, which matters for the concession decision.

**Nine older delivery-note scans** (September to mid-November) were added to `receiving/DC-HAM/`. Not reviewed yet.

## 2026-11-21 16:09 snapshot

Snapshot `2615a73134ffad8f`, 313 files (10 added, 1 changed, 0 removed).

### Added
- `soony/context/launch_status.xlsx`
- `soony/context/memo_launch_priorities.docx`
- `soony/context/org_chart_v2.pdf`
- `soony/master/bom_delta_2026-11-21.csv`
- `soony/master/components_update_2026-11-21.csv`
- `suppliers/SUP-0010_Hwaseong_Memory/order_confirmations/Shipping_advice_020-48113256_4500318735.pdf`
- `suppliers/SUP-0011_Boise_Semi/order_confirmations/OA26144214_4500318769.pdf`
- `suppliers/SUP-0028_Karton_Nowak/notices/Oferta_tryb_ekspresowy_2026-11-21.pdf`
- `suppliers/SUP-0028_Karton_Nowak/order_confirmations/OA26293887_4500318775.pdf`
- `suppliers/SUP-0029_Guangzhou_PackRight/order_confirmations/PL_NHMU7718206_4500318752.pdf`

### Changed
- `soony/master/products.csv` (402 → 470 bytes)

### What it means
Read on Sat 21 Nov, 16:00. Quantities marked "estimate" are derived from ERP stock of Fri 18:00 minus what was packed since; nothing was counted.

**Progress** (`launch_status.xlsx`, Sat 13:00): Standard 554,000 packed, 86,000 to go (14.3 h at 6,000/h). Collector's 53,100 packed, 18,900 to go (21 h at 900/h, with 23 h of shifts left).

**New priorities** (`memo_launch_priorities.docx`, CPO): Collector's Edition gets short parts first, game cards included. No copy ships with an unreleased part; Quality & Compliance decides. Air freight and rush orders above policy limits go to the CPO the same hour, with cost against copies gained. He wants one page per day on what can stop a line.

**Sleeves: the new top risk for Standard.** ECN-2026-118 (`bom_delta`) moves the GH6 sleeve CMP-GAM-004 from rev B to rev C (new USK mark), effective today, and rev B must not be packed.
- ERP shows 186,000 sleeves in stock with no revision recorded. If they are rev B, they are blocked. To confirm at the DC.
- Rev C inbound before launch: only the 20,000 from Karton Nowak (`OA26293887_4500318775.pdf`), due at DC Hamburg tonight. Against 86,000 Standard copies still to pack.
- The 150,000 from PackRight in container NHMU7718206 are rev B (`PL_NHMU7718206_4500318752.pdf`, scan) and arrive 3 Dec anyway.
- Nowak offers rush print of up to 50,000 sleeves in 36 h at +35 %, but their press is down Sat 14:00 to Mon 06:00, so this does not help before Sunday 20:00 unless they confirm otherwise.
- Nowak states the rev C artwork came from Soony Marketing on 2026-08-07. The revision existed for three months before it reached the bill of materials.

**Game cards: the air shipment came short.** Hwaseong flew 28,000 of 48,000 (`Shipping_advice_020-48113256`); the carrier offloaded 2 of 7 ULDs. The other 20,000 reach Hamburg on 24 Nov. The ERP still shows the full 48,000 as booked.
- Estimate: about 70,100 in stock + 28,000 = 98,100 against 104,900 needed, so roughly 6,800 short. Under the memo these come off Standard, not Collector's.
- Boise's 36,000 (`OA26144214_4500318769.pdf`) are packed but held at their dock: the PO says DDP Hamburg, the contract says EXW Boise, and they want written confirmation. Confirmed date is 23 Nov, after launch either way.

**Art books: a fix is on offer.** Karton Nowak has 8,000 art books from a production overrun in stock, at contract price, loaded within 4 h of the order, 9 h by truck (`Oferta_tryb_ekspresowy_2026-11-21.pdf`). That covers the roughly 5,900 shortfall from the first review. The offer is valid 24 h from 21 Nov.

**Smaller changes**
- ECN-2026-119: poster CMP-GAM-009 goes rev A to B, old revision may be used up. No impact.
- `components_update`: statue CMP-GAM-010 is now flagged critical. The CMP-GAM-001 row (A to A) changes nothing.
- `org_chart_v2.pdf`: Arjun Krishnan becomes Category Lead Collector's Items on 23 Nov. That is after launch, so the statue concession still has no second signatory before Sunday.
- `products.csv`: column `plan_weekly_units` renamed to `weekly_plan_qty`; new columns `day_one_qty` (640,000 Standard, 72,000 Collector's) and `valid_from`. Nothing in `explorer/` reads the old name.

**Watch out**
- `bom.csv` and `components.csv` were not updated. The delta files have to be applied on top, otherwise the sleeve still reads rev B.
- The ERP exports are unchanged: stock snapshot is still 2026-11-20 and shipment 04311 still says 48,000.

## 2026-11-20 snapshot (baseline)

Snapshot `730a0852cf6fe9f1`, 303 files. First download from the portal. Reviewed in `../notes/data-findings.md`.

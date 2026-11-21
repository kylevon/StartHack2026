# Soony data changelog

One entry per portal snapshot, newest first. The data itself is not in git: get it with `python3 scripts/update_data.py --apply` (see `README.md` here).

<!-- new entries go below this line -->

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

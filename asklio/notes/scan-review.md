# Scan and contract review (Sat 21 Nov, 18:30)

Snapshot `595614300a5b0101` (21 Nov 18:05). Scans were read with Gemini 2.5 Pro on Vertex AI by `explorer/read_scans.py`; the raw readings are in `data/extracted/` (gitignored, one JSON per file). Re-run that script after a data drop: only new files cost a call.

## Coverage

| What | Files | Read |
|---|---|---|
| Delivery-note scans (`soony/receiving/DC-HAM/`) | 60 | all 60 |
| Scanned PDFs without a text layer | 3 | all 3 (2 contracts, 1 packing list) |
| PDFs with a text layer (4 contracts, 203 order confirmations, notices, context) | 214 | parsed as text by `explorer/build.py`, no vision model needed |

**There is nothing left to scan.** The "323 of 392 goods receipts without a scan" are receipts for which Soony never filed a delivery note in the data. Those bookings cannot be checked against paper at all; only a count at the DC or the supplier's own dispatch record can confirm them.

## Delivery notes: 60 scans, 70 booked lines

- **68 lines match** the goods receipt exactly.
- **1 mismatch:** `20261118_WZ-261116-473.jpg`, art books CMP-GAM-008. Printed 80.000 is struck through and 8 000 written by hand; receiving booked 80,000 (GR 5000413065) against a PO line for 8,000. 72,000 art books in the ERP do not exist.
- **1 to check by eye:** `20261116_DN-261112-486.jpg`, game cards CMP-GAM-001 (GR 5000413062, 68,000). A stamp covers the unit field and the model read the unit as overwritten; the package count "34" is handwritten. The quantity itself matches. Probably a misreading caused by the stamp.
- PackRight's notes use its own part numbers (PR-CC-0312, PR-RB-2207, PR-SL-0604). The cross-reference is Annex C of its contract.
- The three pin deliveries from Dongguan (PRM-GH6-PIN, 24,000 + 24,000 + 30,000) match their paper. The quantities are right; what is missing is a purchase order.

## Packing list (scan, new in the 21 Nov 16:09 drop)

`SUP-0029_Guangzhou_PackRight/order_confirmations/PL_NHMU7718206_4500318752.pdf`: 150,000 sleeves PR-SL-0604 for PO 4500318752, container NHMU7718206, Yantian to Hamburg, ETD 30 Oct. **Artwork: rev. B (GH6_sleeve_revB.pdf).** Since ECN-2026-118 these may not be packed.

## Contracts

Two are scans (Karton Nowak, Dongguan), four have a text layer. Clauses that matter for the open problems:

| Supplier | Clause | What it says | Why it matters |
|---|---|---|---|
| Karton Nowak | §6.2 | Prints to the artwork file last released by Soony in writing | Nowak printing rev C since Marketing's file of 7 Aug is correct. Its sleeves in stock should be rev C. |
| Guangzhou PackRight | §6.2 | Prints to the drawing revision in Soony's component master at the date of the PO | The master said rev B until today, so PackRight's rev B sleeves (64,000 in stock, 150,000 at sea) conform to the contract. Soony cannot reject them at PackRight's cost. |
| Karton Nowak | §3.2 | Rush: up to 50,000 printed parts in 36 h from print-ready artwork, +35 %, express truck DAP Hamburg | The rush offer in the notice is a contract right, not a favour. The press shutdown still makes it too late for Sunday. |
| Guangzhou PackRight | §8 | Force majeure explicitly includes government export restrictions on rare-earth materials; notify within 48 h and propose mitigation | The magnet delay carries no late-delivery penalty. PackRight has notified and proposed other closures, so it is compliant. |
| Guangzhou PackRight | §9, Annex B | Sub-suppliers of critical materials are disclosed; Annex B names Jiangxi RareMag (Ganzhou) for the lid magnets | The single-source magnet risk was on file since 2023. Annex A: the magnets are "fitted by Supplier, 4 per CMP-GAM-007" and included in the box price, which confirms the bill-of-materials line is wrong. |
| Boise Semi | §4, §4.1 | EXW Boise; freight, insurance and duties are the buyer's | The PO says DDP Hamburg. This is why 36,000 game cards are held at Boise's dock. Under the contract, Soony has to arrange and pay the freight. |
| Boise Semi | §9 | No liability for indirect or consequential damages | No claim for launch losses. |
| Hwaseong Memory | §12 | Expires 31 Dec 2026; renewal needs a signed amendment by **15 Dec 2026**; otherwise list prices and no capacity reservation | The main game-card source falls out of contract in six weeks. Nothing in the data shows a renewal under way. |
| Hwaseong Memory | §4 | FOB Busan | Air freight from Incheon is outside the standard terms; who pays for it is not stated. |
| Dongguan | §3.2 | Chinese New Year shutdown up to 12 days, schedule due by 30 Nov | Watch for the notice in the next days. |
| Dongguan | Annex A | Statue CMP-GAM-010 at 83.31 CNY, lead time 77 days | Soony's own statue POs to Dongguan are above this: 4 lines at 85.81 and 13 at 88.38 CNY (about 6 % over), matching the two +3 % price notices. The contract has no clause that allows a price change by notice. |
| All | §7 | Late delivery 0.5 % per week, capped at 5 % | Penalties are small next to the cost of a missed launch. |
| Pune Diecast | §9 | Discloses sub-suppliers only on request | Weaker than PackRight's clause. |

## What this changes

1. **Sleeves:** the contracts explain the revision mix. Nowak's batches (122,000 in stock) should be rev C, PackRight's (64,000) rev B. To confirm on the floor before the lines run out of Nowak stock.
2. **Boise:** confirming EXW in writing releases the 36,000 game cards. They would still arrive on 23 Nov, after the launch.
3. **Hwaseong renewal by 15 Dec** is a new deadline nobody has flagged.
4. **Magnets:** no claim against PackRight; the lever is the alternative closure it offers to sample.

## Confirmed by the suppliers (email, Sat 21 Nov 18:40 CET)

Threads are in the team inbox (`notes/email.md`).

- **Karton Nowak:** WZ-261116-473 was 8,000 art books, not 80,000. WZ-261101-690 and WZ-261110-805 (the 122,000 sleeves in stock) were printed to **rev C**. Our written call-off for 8,000 art books against PO 4500318775 line 1 (EUR 16,800) is accepted and being picked; truck details, ETA and express cost are still to come.
- **Guangzhou PackRight:** the 64,000 sleeves on SN-261014-585 (GR 5000413064) are **rev B**. They must be blocked. Whether the cartons show the revision is still open.
- **Pune Diecast:** calls the paint defects cosmetic, will support a 100 % sort at the Hamburg DC and bear "reasonable" sorting cost; criteria and the name of who attends are still to come. Replacement or credit only after the sort.
- **Hwaseong:** no flight can bring any of the remaining 20,000 game cards to Europe before Sunday 15:00. Earliest is Hamburg on Tue 24 Nov. Arrival of the 28,000 in Frankfurt has to be confirmed with the carrier.
- **Boise:** cannot deliver before 23 Nov and will not release the 36,000 game cards without Soony's written EXW confirmation or a nominated forwarder. Given at 18:47 CET: EXW Boise confirmed for PO 4500318769 and release requested; the DDP term on the PO has to be corrected in SAP.

The DC street address used in the first emails to Nowak and Pune is not in Soony's data. Both were told to use the ship-to address of their earlier deliveries. Do not put a street address for the DC in any mail.

## Supplier status, Sat 21 Nov 21:05 CET

Three hours of email with all six suppliers. Confirmed facts only:

- **Statues, lot of 5,600 in Hamburg (Pune, PO 4500318727):** at 21:05 Pune formally **requested a deviation** to use the lot after a 100 % visual sort, stated the defect is cosmetic (dimensions, weight, function and safety unaffected), and gave the criteria: reject clearly visible paint runs on the base or exposed/uncoated metal at the base edge under normal inspection lighting; accept minor edge-coverage variation not visible in the packed presentation. It proposes to bear reasonable sorting cost and review credit for rejects, subject to internal confirmation. Head of Quality sign-off and photos to follow. Soony's Supplier Quality and Quality & Compliance still have to accept it.
- **Game cards:** Hwaseong confirms the 28,000 (AWB 020-48113256) **arrived in Frankfurt** on 21 Nov. Truck to Hamburg: Soony's transport instruction (own name, cost, risk, up to EUR 5,000) is with Hwaseong's forwarder, not yet booked. Remaining 20,000: Hamburg 24 Nov, final. Boise: 36,000 released on the booked flight (Frankfurt 23 Nov); a courier split of 7,000 is being checked, not booked.
- **Art books:** 8,000 ready at Nowak as finished stock (the bindery shutdown does not affect dispatch). No truck confirmed. Asked Nowak to load them on a truck Warta Trans already has booked (refs PO 7K21M and PO 7703M).
- **Statues by air:** neither Dongguan nor Pune has confirmed any finished stock or flight. Both say their contact cannot accept an order instruction by email; a released PO change is required.
- **Game cases:** PackRight has no role after hand-over FOB Yantian; collection of NHSU4471921 is between Soony and Nordhav.

Offers made in Soony's name, none used so far: Boise transport up to USD 25,000 plus USD 5,000 handling fee; Dongguan freight up to EUR 40,000 plus 20 % premium on statues arriving by Sunday 17:00; Pune freight up to EUR 40,000; Nowak express truck up to EUR 5,000; Frankfurt to Hamburg truck up to EUR 5,000. Boise, Hwaseong and Dongguan were told Soony intends to stop doing business with them if they do not support the launch.

Mail to a supplier in a thread of about twelve messages bounces ("line too long"). Start a new thread instead of replying.

## Supplier status, Sun 22 Nov 02:10 CET

- **Game cards, courier from Boise: closed.** At 02:01 Boise said nobody in its logistics team is available this weekend. The courier request and the USD 50,000 and USD 5,000 approvals were withdrawn. The 36,000 cards travel as booked (AWB 020-48113304, Frankfurt 23 Nov). Hwaseong's 28,000 arrived on 21 Nov; its other 20,000 arrive 24 Nov. **Standard will be about 6,800 game cards short on launch day.**
- **Art books:** order for 8,000 formally confirmed and accepted (21 Nov 21:23, restated 00:47). Goods ready at Nowak. No vehicle confirmed by 02:10; Nowak's account manager is phoning her warehouse and dispatch. Transport is Nowak's under DAP; Soony pays up to EUR 15,000.
- **Statues:** Pune has not delivered the Quality Head sign-off, a cost commitment, a sorting resource or a courier answer. Formal notice of defect sent 21 Nov 22:20, with consequences listed.
- **Sleeves:** Nowak admitted the mislabelled pallet (4,000 GH5 sleeves in delivery WZ-261120-732) and will send 4,000 rev C on its next truck.

**Watch out when mailing:** in a new thread the suppliers answer as if earlier confirmations had not happened (Nowak asked again for a formal order, Boise said the cards were still on hold). Restate everything already agreed in the first message of any new thread.

## Supplier status, Sun 22 Nov 05:10 CET

- **Statues, lot of 5,600 in Hamburg:** at 05:01 Pune **reconfirmed its deviation request and the sorting criteria** and asked Soony to "proceed with the visual sort under the stated criteria and share the final quantities and cost details". Pune sends nobody to Hamburg. Head of Quality sign-off and the decision on sorting cost and credits "will follow separately". No statues arrive by air on Sunday (Pune, 02:11). Whether the sorted pieces may be packed is for Soony's Supplier Quality and Quality & Compliance.
- **Art books:** no vehicle left Poznan overnight; Nowak's dispatch and warehouse did not answer its own account manager all night. The transport for PO 4500318782 had already left on 21 Nov, so the books could not be added to it. The matter is with Nowak's morning shift as urgent. Books in Hamburg run out about 12:25; each hour of delay after a 04:30 departure costs about 900 Collector's Editions, and after a 10:00 departure the delivery no longer helps.

## Limits

- One model read each scan once. Only the art-book correction was checked by a person against the image.
- Contract terms above are from the model's transcription (scans) or the PDF text layer. Quote the PDF itself, not this note, when writing to a supplier.

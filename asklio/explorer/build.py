#!/usr/bin/env python3
"""Build explorer/data.json from the Soony portal snapshot.

Usage:
    python3 explorer/build.py            # build data.json
    python3 explorer/build.py --serve    # build, then serve on http://localhost:8000/explorer/

Reads data/soony-data/ (unzips data/soony-data.zip if the folder is missing).
Stdlib only; uses `pdftotext` (poppler) for PDF text when it is installed.
Nothing about specific parts or suppliers is hardcoded: every check below is a
generic rule applied to whatever the snapshot contains, so a new drop is picked
up by re-running the build.
"""
# pyright: basic, reportOptionalMemberAccess=false, reportArgumentType=false, reportOptionalIterable=false
from __future__ import annotations

import csv
import hashlib
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # asklio/
DATA = ROOT / "data" / "soony-data"
ZIP = ROOT / "data" / "soony-data.zip"
OUT = Path(__file__).resolve().parent / "data.json"

LAUNCH = dt.datetime(2026, 11, 22, 20, 0)
# Extra road days from arrival point to the DC, by destination code
# (taken from master/routes.csv at runtime; this is only the fallback).
DEFAULT_LAST_MILE = 1


# --------------------------------------------------------------------------- io
def ensure_data() -> None:
    if DATA.exists():
        return
    if not ZIP.exists():
        sys.exit(f"Missing {DATA}. Run: python3 scripts/update_data.py --apply (from the repo root)")
    with zipfile.ZipFile(ZIP) as z:
        z.extractall(DATA.parent)


def read_csv(path: Path, delimiter: str = ",") -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [dict(r) for r in csv.DictReader(f, delimiter=delimiter)]


def num(v):
    if v is None or v == "":
        return None
    try:
        f = float(str(v).replace(",", "."))
        return int(f) if f.is_integer() else f
    except ValueError:
        return v


def rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


# ------------------------------------------------------------------ xlsx (stdlib)
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "pr": "http://schemas.openxmlformats.org/package/2006/relationships"}


def col_index(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_xlsx(path: Path) -> dict[str, list[list]]:
    sheets: dict[str, list[list]] = {}
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = {r.get("Id"): r.get("Target") for r in
                ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).findall("pr:Relationship", NS)}
        for s in wb.find("m:sheets", NS):
            target = rels[s.get(f"{{{NS['r']}}}id")].lstrip("/")
            target = target if target.startswith("xl/") else "xl/" + target
            rows = []
            for row in ET.fromstring(z.read(target)).iter(f"{{{NS['m']}}}row"):
                vals: dict[int, object] = {}
                for c in row.findall("m:c", NS):
                    t, v = c.get("t"), c.find("m:v", NS)
                    if t == "s" and v is not None:
                        val = shared[int(v.text)]
                    elif t == "inlineStr":
                        val = "".join(x.text or "" for x in c.iter(f"{{{NS['m']}}}t"))
                    elif v is not None:
                        val = num(v.text) if t != "str" else v.text
                    else:
                        continue
                    vals[col_index(c.get("r"))] = val
                if vals:
                    rows.append([vals.get(i) for i in range(max(vals) + 1)])
            sheets[s.get("name")] = rows
    return sheets


def table(rows: list[list], header_row: int | None = None) -> list[dict]:
    """Turn sheet rows into dicts, using the first row that looks like a header."""
    if not rows:
        return []
    if header_row is None:
        need = min(3, max(sum(c is not None for c in r) for r in rows))
        header_row = next(i for i, r in enumerate(rows) if sum(c is not None for c in r) >= need)
    hdr = [str(h) if h is not None else f"col{i}" for i, h in enumerate(rows[header_row])]
    out = []
    for r in rows[header_row + 1:]:
        if sum(c is not None for c in r) < min(2, len(hdr)):
            continue
        out.append({hdr[i]: (r[i] if i < len(r) else None) for i in range(len(hdr))})
    return out


# ------------------------------------------------------------------------- pdf
HAS_PDFTOTEXT = shutil.which("pdftotext") is not None


def pdf_text(path: Path) -> str:
    if not HAS_PDFTOTEXT:
        return ""
    try:
        return subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True,
                              text=True, timeout=30).stdout.strip()
    except Exception:
        return ""


OC_LINE = re.compile(r"^\s*(\d{5})\s+(\S+)\s+.*?\s([\d,]+)\s+([\d.]+)\s+([A-Z]{3})\s+(\d{4}-\d{2}-\d{2})\s*$")
OC_HEAD = re.compile(r"(?:Order (?:Confirmation|Acknowledgement)|OA)\s*(OA\d+)?.*", re.I)


def parse_oc(text: str) -> dict:
    oc = {"lines": [], "notes": []}
    m = re.search(r"\b(OA\d{6,})", text)
    oc["oc_number"] = m.group(1) if m else None
    m = re.search(r"Your order (\d+) of (\d{4}-\d{2}-\d{2})", text)
    if m:
        oc["po_number"], oc["po_date"] = m.group(1), m.group(2)
    m = re.search(r"Incoterms ([^·\n]+)", text)
    oc["incoterm"] = m.group(1).strip() if m else None
    in_table, after = False, False
    for line in text.splitlines():
        if re.match(r"^\s*Item\s+Material", line):
            in_table = True
            continue
        lm = OC_LINE.match(line)
        if in_table and lm:
            oc["lines"].append({"item": int(lm.group(1)) // 10, "material_id": lm.group(2),
                                "qty": int(lm.group(3).replace(",", "")), "unit_price": float(lm.group(4)),
                                "currency": lm.group(5), "confirmed_date": lm.group(6)})
            after = True
        elif after and line.strip() and not line.startswith(" " * 20):
            oc["notes"].append(line.strip())
    return oc


# ------------------------------------------------------------- vision cache
EXTRACTED = ROOT / "data" / "extracted"


def extracted_for(path: Path):
    """Result of read_scans.py for this exact file content, if it has been read."""
    f = EXTRACTED / (hashlib.sha256(path.read_bytes()).hexdigest() + ".json")
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def parse_qty(text) -> int | None:
    """'14.000', '68 000', '5,000' -> 14000, 68000, 5000. None if it is not a clean quantity."""
    t = re.sub(r"[\s\u00a0\u202f]", "", str(text or ""))
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", t):
        return int(re.sub(r"[.,]", "", t))
    return int(t) if re.fullmatch(r"\d+", t) else None


# ---------------------------------------------------------------------- build
def main() -> None:
    ensure_data()
    S = DATA / "soony"
    snap_dates = []

    master = {p.stem: read_csv(p) for p in sorted((S / "master").glob("*.csv"))}
    components = {c["component_id"]: c for c in master.get("components", [])}
    products = {p["product_id"]: p for p in master.get("products", [])}
    routes = master.get("routes", [])

    # ------------------------------------------------------------- suppliers
    suppliers = {}
    for d in sorted((DATA / "suppliers").iterdir()):
        if not d.is_dir():
            continue
        prof = read_csv(d / "profile.csv")[0] if (d / "profile.csv").exists() else {"supplier_id": d.name[:8]}
        sid = prof["supplier_id"]
        prof["folder"] = rel(d)
        prof["components"] = read_csv(d / "components.csv") if (d / "components.csv").exists() else []
        for c in prof["components"]:
            for k in ("share", "unit_price", "lead_time_days", "moq"):
                c[k] = num(c[k])
        suppliers[sid] = prof

    # ------------------------------------------------------------- purchase orders
    pos = []
    for p in sorted((S / "erp").glob("purchase_orders*.csv")):
        if "legacy" in p.name:
            def d_us(v):
                return dt.datetime.strptime(v, "%m/%d/%Y").date().isoformat() if v else None
            for r in read_csv(p, ";"):
                sid = f"SUP-{int(r['LIFNR']):04d}"
                pos.append({"po_number": r["EBELN"], "po_line": int(r["EBELP"]) // 10, "supplier_id": sid,
                            "material_id": r["MATNR"], "plant": r["WERKS"], "quantity": num(r["MENGE"]),
                            "unit_price": num(r["NETPR"]), "currency": suppliers.get(sid, {}).get("currency"),
                            "order_date": d_us(r["BEDAT"]), "requested_date": d_us(r["EINDT"]),
                            "promised_date": d_us(r["ZZCONF"]), "actual_delivery_date": d_us(r["WEDAT"]),
                            "status": {"GL": "delivered"}.get(r["ZZSTAT"], r["ZZSTAT"].lower()),
                            "buyer": r["ERNAM"], "incoterm": None, "note": "", "source": p.name})
        else:
            for r in read_csv(p):
                r["po_line"] = int(r["po_line"])
                r["quantity"], r["unit_price"] = num(r["quantity"]), num(r["unit_price"])
                r["source"] = p.name
                pos.append(r)
    po_index = defaultdict(list)
    for r in pos:
        po_index[r["po_number"]].append(r)

    # ------------------------------------------------------------- goods receipts / stock / packout
    grs = read_csv(S / "erp" / "goods_receipts.csv")
    for r in grs:
        r["qty_ordered"], r["qty_received"] = num(r["qty_ordered"]), num(r["qty_received"])
    gr_by_number = {r["gr_number"]: r for r in grs}

    stock = read_csv(S / "erp" / "stock_snapshot.csv")
    for r in stock:
        for k in ("quantity", "safety_stock", "weeks_of_cover"):
            r[k] = num(r[k])
        snap_dates.append(r["snapshot_date"])
    packout = read_csv(S / "erp" / "packout_log.csv")
    for r in packout:
        r["units_packed"] = num(r["units_packed"])

    shipments = read_csv(S / "erp" / "open_shipments.csv")

    # ------------------------------------------------------------- excel files
    launch_plan, tracker = {}, []
    for x in S.rglob("*.xlsx"):
        sheets = read_xlsx(x)
        if "launch_plan" in x.name:
            launch_plan = {"file": rel(x), "title": sheets.get("Editions", [[None]])[0][0],
                           "sheets": {k: table(v) for k, v in sheets.items()}}
        elif "tracker" in x.name:
            tracker = table(next(iter(sheets.values())))
            tracker_file = rel(x)

    # ------------------------------------------------------------- documents
    docs = []
    ocs = []
    inspections = []
    for f in sorted(DATA.rglob("*")):
        if not f.is_file() or f.suffix.lower() in (".csv",):
            continue
        parts = f.relative_to(DATA).parts
        doc = {"path": rel(f), "name": f.name, "ext": f.suffix.lower().lstrip("."),
               "size": f.stat().st_size, "supplier_id": None, "kind": parts[-2] if len(parts) > 1 else "",
               "ref": None, "date": None, "text": ""}
        if parts[0] == "suppliers":
            doc["supplier_id"] = parts[1][:8]
        if parts[-2] == "DC-HAM" and doc["ext"] in ("jpg", "jpeg", "png"):
            doc["kind"] = "delivery_note_scan"
            m = re.match(r"(\d{8})_(.+)\.\w+$", f.name)
            if m:
                doc["date"] = dt.datetime.strptime(m.group(1), "%Y%m%d").date().isoformat()
                doc["ref"] = m.group(2)
        if doc["ext"] == "pdf":
            doc["text"] = pdf_text(f)
            doc["scanned"] = not doc["text"]
        if doc["ext"] in ("jpg", "jpeg", "png") or doc.get("scanned"):
            ex = extracted_for(f)
            if ex:
                doc["read"] = {"model": ex.get("model"), "read_at": ex.get("read_at"), **ex["data"]}
                if ex["kind"] == "document":
                    doc["text"] = ex["data"].get("full_text", "")
                    doc["read"].pop("full_text", None)
                else:
                    for ln in doc["read"].get("lines", []):
                        ln["printed_quantity"] = parse_qty(ln.get("printed_quantity_text"))
                        ln["final_quantity"] = parse_qty(ln.get("final_quantity_text"))
        if doc["ext"] == "xlsx":
            try:
                doc["sheets"] = {k: v for k, v in read_xlsx(f).items()}
            except Exception:
                pass
        if doc["kind"] == "order_confirmations" and doc["text"]:
            oc = parse_oc(doc["text"])
            oc.update({"supplier_id": doc["supplier_id"], "path": doc["path"]})
            ocs.append(oc)
            doc["ref"] = oc.get("po_number")
        if f.name.startswith("inspection_report"):
            gr_no = re.search(r"(\d{10})", f.name)
            rejected = bool(re.search(r"does not meet|reject(ed)?\b(?!\s*number)", doc["text"], re.I)) and \
                not re.search(r"Lot (meets|accepted)", doc["text"], re.I)
            inspections.append({"gr_number": gr_no.group(1) if gr_no else None, "path": doc["path"],
                                "rejected": rejected, "text": doc["text"]})
        docs.append(doc)
    scans_by_ref = {d["ref"]: d["path"] for d in docs if d["kind"] == "delivery_note_scan"}
    for r in grs:
        r["scan"] = scans_by_ref.get(r["delivery_note"])

    # ------------------------------------------------------------- derived: remaining demand
    editions = launch_plan.get("sheets", {}).get("Editions", [])
    remaining = {}
    for e in editions:
        pid = e.get("Product")
        if pid:
            remaining[pid] = {"edition": e.get("Edition"), "demand": num(e.get("Day-one demand")),
                              "preorders": num(e.get("of which pre-orders")), "packed": num(e.get("Packed")),
                              "rate_per_hour": num(e.get("Rate per hour")),
                              "hours_available": num(e.get("Hours available"))}
    # packed from stock snapshot is the system truth; prefer it when present
    for r in stock:
        if r["material_id"] in remaining:
            remaining[r["material_id"]]["packed_erp"] = r["quantity"]
    for pid, e in remaining.items():
        e["to_pack"] = (e["demand"] or 0) - (e.get("packed_erp") or e["packed"] or 0)

    today = max(snap_dates) if snap_dates else dt.date.today().isoformat()
    bom = [b for b in master.get("bom", []) if b["valid_from"] <= today <= b["valid_to"]]
    for b in bom:
        b["qty_per"] = num(b["qty_per"])

    # ------------------------------------------------------------- derived: flags
    flags = []

    def cname(mid):
        c = components.get(mid)
        return re.sub(r"\s*\(.*\)$", "", c["description"]) if c else mid

    def flag(sev, cat, title, detail, refs=None, material=None, qty=None):
        flags.append({"severity": sev, "category": cat, "title": title, "detail": detail,
                      "refs": refs or [], "material_id": material, "qty": qty})

    no_po = defaultdict(list)
    launch_parts = {b["child_id"] for b in bom if b["parent_id"] in remaining}
    blocked_batches = {}   # batch -> qty that should not be counted
    inflated_batches = {}  # batch -> qty booked above what was ordered

    for ins in inspections:
        gr = gr_by_number.get(ins["gr_number"])
        if ins["rejected"] and gr:
            in_stock = next((s for s in stock if s["batch"] == gr["gr_number"]), None)
            q = in_stock["quantity"] if in_stock else gr["qty_received"]
            if in_stock:
                blocked_batches[gr["gr_number"]] = q
            flag("critical", "Quality", f"Rejected lot counted as usable stock: {cname(gr['material_id'])}",
                 f"Incoming inspection rejected GR {gr['gr_number']} ({gr['qty_received']:,} pcs from "
                 f"{gr['supplier_id']}), but the batch sits in ERP stock{' as ' + format(q, ',') + ' pcs' if in_stock else ''}.",
                 [ins["path"]] + ([gr["scan"]] if gr.get("scan") else []), gr["material_id"], q)

    # ---- paper vs ERP: what the scanned delivery note says vs what receiving booked
    def resolve_material(ln):
        """Scan lines may carry the supplier's own part number: fall back to the description."""
        if ln.get("material_id") in components:
            return ln["material_id"]
        d = (ln.get("description") or "").strip().lower()
        for n in (len(d), 24, 18):   # scans truncate long descriptions: try the longest prefix first
            hits = [cid for cid, c in components.items() if d and c["description"].lower().startswith(d[:n])]
            if len(hits) == 1:
                return hits[0]
        return ln.get("material_id")

    paper_checks = []
    paper_confirmed = set()   # GR numbers whose booked quantity equals the paper
    paper_mismatch = set()
    grs_by_note = defaultdict(list)
    for r in grs:
        grs_by_note[r["delivery_note"]].append(r)
    own_numbers = defaultdict(set)
    scans_read = [d for d in docs if d["kind"] == "delivery_note_scan" and d.get("read")]
    for d in scans_read:
        booked = list(grs_by_note.get(d["ref"], []))
        lines = d["read"].get("lines", [])
        for ln in lines:
            ln["soony_material_id"] = resolve_material(ln)
            if ln["soony_material_id"] != ln.get("material_id") and ln["soony_material_id"] in components:
                own_numbers[d["path"].split("/")[-1].split("_")[1][:2], d["read"].get("supplier_name")].add(ln.get("material_id"))
        if not booked:
            paper_checks.append({"path": d["path"], "ref": d["ref"], "result": "no_booking",
                                 "detail": "Delivery note scanned, but no goods receipt references it."})
            flag("warning", "Receiving", f"Delivery note {d['ref']} has no goods receipt",
                 "The scan exists, but nothing in the ERP references this note.", [d["path"]])
            continue
        # pair identical lines first, then whatever is left over per material
        left_l, left_b = list(lines), list(booked)
        for ln in list(left_l):
            m = next((b for b in left_b if b["material_id"] == ln["soony_material_id"] and b["qty_received"] == ln["final_quantity"]), None)
            if m:
                left_l.remove(ln); left_b.remove(m)
                paper_confirmed.add(m["gr_number"])
                paper_checks.append({"path": d["path"], "ref": d["ref"], "gr_number": m["gr_number"], "material_id": m["material_id"],
                                     "paper": ln["final_quantity"], "booked": m["qty_received"], "result": "match",
                                     "hand_corrected": bool(ln.get("handwritten_correction") and ln.get("corrected_field") == "quantity")})
        for ln in list(left_l):
            m = next((b for b in left_b if b["material_id"] == ln["soony_material_id"]), None)
            if not m:
                paper_checks.append({"path": d["path"], "ref": d["ref"], "material_id": ln["soony_material_id"],
                                     "paper": ln["final_quantity"], "result": "not_booked",
                                     "detail": "On the paper, not in the ERP."})
                flag("warning", "Receiving", f"On delivery note {d['ref']} but not booked: {cname(ln['soony_material_id'])}",
                     f"The paper lists {ln.get('final_quantity_text')} × {ln['soony_material_id']}; no goods receipt line matches.", [d["path"]],
                     ln["soony_material_id"])
                continue
            left_l.remove(ln); left_b.remove(m)
            paper, bk = ln["final_quantity"], m["qty_received"]
            corrected = ln.get("handwritten_correction") and ln.get("corrected_field") == "quantity"
            if paper is None:
                paper_checks.append({"path": d["path"], "ref": d["ref"], "gr_number": m["gr_number"], "material_id": m["material_id"],
                                     "paper": None, "booked": bk, "result": "unreadable",
                                     "detail": f"Quantity text '{ln.get('final_quantity_text')}' could not be parsed."})
                continue
            paper_mismatch.add(m["gr_number"])
            in_stock = next((x for x in stock if x["batch"] == m["gr_number"]), None)
            if in_stock and bk > paper:
                inflated_batches[m["gr_number"]] = min(in_stock["quantity"], bk - paper)
            paper_checks.append({"path": d["path"], "ref": d["ref"], "gr_number": m["gr_number"], "material_id": m["material_id"],
                                 "paper": paper, "printed": ln.get("printed_quantity"), "booked": bk, "ordered": m["qty_ordered"],
                                 "result": "mismatch", "hand_corrected": bool(corrected)})
            how = (f"The printed {ln.get('printed_quantity_text')} is struck through and {ln.get('final_quantity_text')} is written by hand. "
                   if corrected else "")
            flag("critical", "Receiving", f"Paper says {paper:,}, ERP booked {bk:,}: {cname(m['material_id'])}",
                 f"Delivery note {d['ref']} (read from the scan). {how}Receiving booked {bk:,} as GR {m['gr_number']} on {m['gr_date']} "
                 f"({m['remark'] or 'no remark'}); the PO line is for {m['qty_ordered']:,}. "
                 f"{abs(bk - paper):,} pcs in the system {'do not exist' if bk > paper else 'are missing from the books'}.",
                 [d["path"]], m["material_id"], abs(bk - paper))
        for b in left_b:
            paper_checks.append({"path": d["path"], "ref": d["ref"], "gr_number": b["gr_number"], "material_id": b["material_id"],
                                 "booked": b["qty_received"], "result": "not_on_paper", "detail": "Booked, but not on the paper."})
            flag("warning", "Receiving", f"Booked but not on delivery note {d['ref']}: {cname(b['material_id'])}",
                 f"GR {b['gr_number']} books {b['qty_received']:,} × {b['material_id']}, which the scanned note does not list.", [d["path"]],
                 b["material_id"], b["qty_received"])
        # corrections that are not about quantity, and pen notes: worth a human look, the model can misread stamps
        for ln in lines:
            if ln.get("handwritten_correction") and ln.get("corrected_field") != "quantity":
                stamp = any("stamp" in a.lower() for a in d["read"].get("anomalies", []))
                paper_checks.append({"path": d["path"], "ref": d["ref"], "material_id": ln["soony_material_id"], "result": "to_verify",
                                     "detail": f"Possible handwritten change to {ln.get('corrected_field') or 'a field'}: {ln.get('correction_note')}"
                                               + (" A stamp overlaps this area, so this may be a misread." if stamp else "")})
    for (_, sup_name), nums in own_numbers.items():
        flag("info", "Master data", f"{sup_name} uses its own part numbers on delivery notes",
             f"{', '.join(sorted(nums))}: matched to Soony parts by description.", [])
    if scans_read:
        n_match = sum(1 for c in paper_checks if c["result"] == "match")
        flag("info", "Receiving", f"{len(scans_read)} delivery-note scans read: {n_match} booked lines confirmed by the paper",
             f"{sum(1 for c in paper_checks if c['result'] == 'mismatch')} quantity mismatch(es), "
             f"{sum(1 for c in paper_checks if c['result'] == 'to_verify')} reading(s) to verify by eye. "
             f"{sum(1 for r in grs if not r.get('scan'))} of {len(grs)} goods receipts have no scan to check against.", [])

    for r in grs:
        o, rcv = r["qty_ordered"], r["qty_received"]
        r["paper"] = "match" if r["gr_number"] in paper_confirmed else "mismatch" if r["gr_number"] in paper_mismatch else None
        if not r["po_number"]:
            no_po[(r["supplier_id"], r["material_id"])].append(r)
        elif r["gr_number"] in paper_confirmed or r["gr_number"] in paper_mismatch:
            pass  # the scan has been read: the paper comparison above is the better evidence
        elif o and rcv and rcv >= 1.5 * o:
            in_stock = next((s for s in stock if s["batch"] == r["gr_number"]), None)
            if in_stock:
                inflated_batches[r["gr_number"]] = min(in_stock["quantity"], rcv - o)
            flag("critical", "Receiving", f"Booked {rcv / o:.0f}× the ordered quantity: {cname(r['material_id'])}",
                 f"GR {r['gr_number']} on {r['gr_date']}: ordered {o:,}, booked {rcv:,} ({r['remark'] or 'no remark'}). "
                 f"The delivery note {r['delivery_note']} has not been read yet: check it.",
                 [r["scan"]] if r.get("scan") else [], r["material_id"], rcv - o)

    for (sup, mat), rs in no_po.items():
        tot = sum(r["qty_received"] or 0 for r in rs)
        flag("warning", "Receiving", f"{tot:,} × {mat} received without any PO",
             f"{len(rs)} receipt(s) from {sup} ({', '.join(r['gr_date'] for r in rs)}). Remark: {rs[0]['remark']}",
             [r["scan"] for r in rs if r.get("scan")], mat, tot)

    # shipments
    last_mile = {r["origin"]: int(r["transit_days"]) for r in routes if r["destination"] == "DC-HAM"}
    max_update = max((s["updated_at"] for s in shipments), default="")
    inbound = defaultdict(list)
    for s in shipments:
        eta = dt.date.fromisoformat(s["eta"])
        extra = 0 if s["destination"] == "DC-HAM" else last_mile.get(s["destination"], DEFAULT_LAST_MILE)
        s["eta_dc"] = (eta + dt.timedelta(days=extra)).isoformat()
        s["before_launch"] = s["eta_dc"] <= LAUNCH.date().isoformat()
        mats = s["material_ids"].split("|")
        s["lines"] = []
        for po in s["po_numbers"].split("|"):
            for line in po_index.get(po, []):
                if line["material_id"] in mats and line["status"] in ("open", "awaiting_approval"):
                    s["lines"].append({"po_number": po, "po_line": line["po_line"],
                                       "material_id": line["material_id"], "quantity": line["quantity"]})
                    inbound[line["material_id"]].append({"shipment_id": s["shipment_id"], "po_number": po,
                                                         "qty": line["quantity"], "eta_dc": s["eta_dc"],
                                                         "before_launch": s["before_launch"],
                                                         "status": s["status"], "mode": s["mode"]})
        try:
            age_h = (dt.datetime.fromisoformat(max_update) - dt.datetime.fromisoformat(s["updated_at"])).total_seconds() / 3600
        except ValueError:
            age_h = 0
        s["stale_hours"] = round(age_h, 1)
        if s["before_launch"] and s["status"] in ("booked",) and s["eta_dc"] >= today and launch_parts & set(mats):
            flag("warning", "Logistics", f"Launch-critical shipment not yet moving: {', '.join(cname(m) for m in mats)} ({s['shipment_id']})",
                 f"{s['mode']} {s['origin']}→{s['destination']} for {', '.join(mats)}, status '{s['status']}', "
                 f"must reach DC-HAM by {s['eta_dc']} (launch {LAUNCH:%a %d %b %H:%M}).", [], mats[0])
        if s["status"] == "arrived_port":
            flag("warning", "Logistics", f"Sitting at the port: {', '.join(cname(m) for m in mats)} ({s['shipment_id']})",
                 f"{', '.join(mats)} at {s['destination']}: {s['note']}. Needs pick-up and a dock slot.", [], mats[0])

    # tracker vs ERP
    erp_ids = {s["shipment_id"]: s for s in shipments}
    trk_ids = {t.get("Shipment"): t for t in tracker if t.get("Shipment")}
    tracker_diff = []
    for sid, s in erp_ids.items():
        t = trk_ids.get(sid)
        if not t:
            tracker_diff.append({"shipment_id": sid, "issue": "missing in tracker", "erp": s["status"], "tracker": None})
        elif str(t.get("Status", "")).replace(" ", "_") != s["status"]:
            tracker_diff.append({"shipment_id": sid, "issue": "status differs", "erp": s["status"],
                                 "tracker": t.get("Status"), "comment": t.get("Comment")})
    for sid in trk_ids.keys() - erp_ids.keys():
        tracker_diff.append({"shipment_id": sid, "issue": "not in ERP", "erp": None, "tracker": trk_ids[sid].get("Status")})
    if tracker_diff:
        flag("info", "Logistics", f"Shipment tracker disagrees with the ERP on {len(tracker_diff)} shipments",
             "The spreadsheet tracker is missing shipments or shows stale statuses.", [tracker_file])

    # BOM lines with no stock that the supplier fits itself
    fitted = {}
    for sup in suppliers.values():
        for c in sup["components"]:
            if re.search(r"fitted by supplier|not ordered, received or stocked", c.get("note") or "", re.I):
                fitted[c["component_id"]] = f"{sup['name']}: {c['note']}"

    # conditional suppliers past their window (policy text parsed for the day limit)
    policy_text = " ".join(d["text"] for d in docs if "policy" in d["name"].lower())
    m = re.search(r"Conditional releases are limited to (\d+) days", policy_text)
    cond_days = int(m.group(1)) if m else None
    for sup in suppliers.values():
        if sup.get("qualification_status") == "conditional" and cond_days:
            start = dt.date.fromisoformat(sup["supplier_since"])
            exp = start + dt.timedelta(days=cond_days)
            sup["conditional_expires"] = exp.isoformat()
            waiting = [p for p in pos if p["supplier_id"] == sup["supplier_id"] and p["status"] == "awaiting_approval"]
            if exp.isoformat() < today:
                flag("warning", "Policy", f"Conditional release expired: {sup['name']}",
                     f"Conditional since {start}, {cond_days}-day limit (policy) ended {exp}. "
                     f"{len(waiting)} PO line(s) awaiting approval. Extension needs the Category Lead and Supplier Quality Lead.",
                     [d["path"] for d in docs if "policy" in d["name"].lower()])

    # order confirmations vs POs
    oc_issues = []
    for oc in ocs:
        for ln in oc["lines"]:
            po = next((p for p in po_index.get(oc.get("po_number"), []) if p["po_line"] == ln["item"]), None) or \
                 next((p for p in po_index.get(oc.get("po_number"), []) if p["material_id"] == ln["material_id"]), None)
            if not po:
                oc_issues.append({**ln, "po_number": oc.get("po_number"), "supplier_id": oc["supplier_id"],
                                  "issue": "no matching PO line", "path": oc["path"]})
                continue
            if po["quantity"] != ln["qty"]:
                oc_issues.append({**ln, "po_number": po["po_number"], "supplier_id": oc["supplier_id"],
                                  "issue": f"qty PO {po['quantity']:,} vs OC {ln['qty']:,}", "path": oc["path"]})
            if po.get("unit_price") and abs(float(po["unit_price"]) - ln["unit_price"]) > 1e-6:
                oc_issues.append({**ln, "po_number": po["po_number"], "supplier_id": oc["supplier_id"],
                                  "issue": f"price PO {po['unit_price']} vs OC {ln['unit_price']}", "path": oc["path"]})
            if po.get("promised_date") and po["promised_date"] != ln["confirmed_date"]:
                oc_issues.append({**ln, "po_number": po["po_number"], "supplier_id": oc["supplier_id"],
                                  "issue": f"date PO {po['promised_date']} vs OC {ln['confirmed_date']}", "path": oc["path"]})
        for note in oc["notes"]:
            rev = re.search(r"rev\.?\s*([A-Z])\b", note)
            for ln in oc["lines"]:
                c = components.get(ln["material_id"])
                if rev and c and ln["material_id"] in note and c.get("drawing_rev") and c["drawing_rev"] != rev.group(1):
                    oc_issues.append({**ln, "po_number": oc.get("po_number"), "supplier_id": oc["supplier_id"],
                                      "issue": f"artwork rev {rev.group(1)} vs master rev {c['drawing_rev']}",
                                      "path": oc["path"], "note": note})
            if re.search(r"approved for serial supply", note, re.I):
                sup = suppliers.get(oc["supplier_id"], {})
                if sup.get("qualification_status") != "qualified":
                    oc_issues.append({"po_number": oc.get("po_number"), "supplier_id": oc["supplier_id"],
                                      "issue": f"supplier claims serial approval, master says '{sup.get('qualification_status')}'",
                                      "path": oc["path"], "note": note})
    # summarise rev / approval mismatches as flags (one per distinct issue)
    seen = set()
    for i in oc_issues:
        if i["issue"].startswith(("artwork rev", "supplier claims")) and (i["issue"], i["supplier_id"]) not in seen:
            seen.add((i["issue"], i["supplier_id"]))
            n = sum(1 for j in oc_issues if j["issue"] == i["issue"] and j["supplier_id"] == i["supplier_id"])
            flag("warning", "Release gate", f"{suppliers.get(i['supplier_id'], {}).get('name', i['supplier_id'])}: {i['issue']}",
                 f"Found in {n} order confirmation(s). {i.get('note', '')}", [i["path"]], i.get("material_id"))

    price_diffs = [i for i in oc_issues if i["issue"].startswith("price")]
    for sup in sorted({i["supplier_id"] for i in price_diffs}):
        rows = [i for i in price_diffs if i["supplier_id"] == sup]
        flag("info", "Contracts", f"{suppliers.get(sup, {}).get('name', sup)} confirmed higher prices than ordered on {len(rows)} PO(s)",
             "; ".join(f"{i['po_number']}: {i['issue']}" for i in rows), [i["path"] for i in rows], rows[0].get("material_id"))

    # ------------------------------------------------------------- derived: component coverage
    coverage = []
    for cid, c in components.items():
        users = [b for b in bom if b["child_id"] == cid and b["parent_id"] in remaining]
        if not users:
            continue
        need = sum(b["qty_per"] * remaining[b["parent_id"]]["to_pack"] for b in users)
        batches = [s for s in stock if s["material_id"] == cid]
        erp = sum(s["quantity"] for s in batches)
        blocked = sum(blocked_batches.get(s["batch"], 0) for s in batches)
        inflated = sum(inflated_batches.get(s["batch"], 0) for s in batches)
        adjusted = erp - blocked - inflated
        inb = inbound.get(cid, [])
        before = sum(i["qty"] for i in inb if i["before_launch"])
        coverage.append({"component_id": cid, "description": c["description"], "category": c["category"],
                         "per": {b["parent_id"]: b["qty_per"] for b in users}, "needed": need,
                         "erp_stock": erp, "blocked": blocked, "inflated": inflated, "adjusted": adjusted,
                         "inbound_before_launch": before, "inbound_after_launch": sum(i["qty"] for i in inb if not i["before_launch"]),
                         "inbound": inb, "batches": batches, "fitted_by_supplier": fitted.get(cid),
                         "suppliers": [{"supplier_id": s["supplier_id"], "name": s["name"], **sc}
                                       for s in suppliers.values() for sc in s["components"] if sc["component_id"] == cid],
                         "last_count": max((s["last_count"] for s in batches), default=None)})

    # buildable units per edition: ERP view vs adjusted view (plus inbound before launch)
    buildable = {}
    for pid, e in remaining.items():
        lines = [c for c in coverage if pid in c["per"] and not c["fitted_by_supplier"]]

        def cap(key, add_inbound=False):
            best = None
            for c in lines:
                avail = c[key] + (c["inbound_before_launch"] if add_inbound else 0)
                # shared parts: assume the other editions take their share first is unknowable,
                # so cap against this edition's own need share proportionally
                share = c["per"][pid] * e["to_pack"] / c["needed"] if c["needed"] else 1
                units = int(avail * share // c["per"][pid])
                if best is None or units < best[0]:
                    best = (units, c["component_id"])
            return {"units": min(best[0], e["to_pack"]) if best else e["to_pack"], "limited_by": best[1] if best else None}
        buildable[pid] = {"erp": cap("erp_stock"), "erp_plus_inbound": cap("erp_stock", True),
                          "adjusted": cap("adjusted"), "adjusted_plus_inbound": cap("adjusted", True)}

    for c in coverage:
        gap = c["adjusted"] + c["inbound_before_launch"] - c["needed"]
        if gap < 0 and not c["fitted_by_supplier"]:
            flag("critical", "Shortage", f"Short {-gap:,} × {cname(c['component_id'])}",
                 f"Need {c['needed']:,} for the remaining pack-out; ERP shows {c['erp_stock']:,}, "
                 f"of which {c['blocked'] + c['inflated']:,} are not real/usable; {c['inbound_before_launch']:,} inbound before launch.",
                 [], c["component_id"], -gap)
        if c["fitted_by_supplier"] and c["erp_stock"] == 0:
            flag("info", "Master data", f"False alarm: {cname(c['component_id'])}",
                 f"BOM asks for {c['needed']:,} but {c['fitted_by_supplier']}", [], c["component_id"])

    sev_rank = {"critical": 0, "warning": 1, "info": 2}
    flags.sort(key=lambda f: (sev_rank[f["severity"]], -(f["qty"] or 0)))

    out = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "snapshot_date": today, "launch": LAUNCH.isoformat(),
        "remaining": remaining, "buildable": buildable, "coverage": coverage, "flags": flags,
        "launch_plan": launch_plan, "products": products, "components": components, "bom": bom,
        "suppliers": suppliers, "purchase_orders": pos, "goods_receipts": grs, "stock": stock,
        "packout": packout, "shipments": shipments, "tracker": tracker, "tracker_diff": tracker_diff,
        "order_confirmations": ocs, "oc_issues": oc_issues, "inspections": inspections, "paper_checks": paper_checks,
        "master": {k: v for k, v in master.items() if k not in ("components", "bom", "products")},
        "documents": docs,
        "context_md": {rel(p): p.read_text(encoding="utf-8") for p in S.rglob("*.md")},
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(flags)} flags, {len(docs)} documents, "
          f"{len(pos)} PO lines, {len(ocs)} order confirmations"
          + ("" if HAS_PDFTOTEXT else " (pdftotext not found: PDF text skipped)"))


if __name__ == "__main__":
    main()
    if "--serve" in sys.argv:
        import functools
        import http.server
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
        print("Serving on http://localhost:8000/explorer/")
        http.server.ThreadingHTTPServer(("127.0.0.1", 8000), handler).serve_forever()

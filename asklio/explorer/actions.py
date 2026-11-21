#!/usr/bin/env python3
# pyright: basic, reportOptionalMemberAccess=false, reportArgumentType=false
"""Turn findings into reconciliation actions: one drafted email per thing somebody has to confirm or do.

Usage:
    python3 explorer/actions.py            # plan and draft emails for new/changed cases
    python3 explorer/actions.py --force    # re-draft everything

Reads explorer/data.json (run build.py first). Groups findings into cases, then asks the
model (Gemini on Vertex AI) to decide, per case, who needs to be written to and to draft the
email in the recipient's language. Writes explorer/actions.json.

Drafts are cached in data/extracted/drafts/ keyed by the case content, so only cases that
changed since the last run cost a model call. Nothing here sends mail: sending happens in
server.py, only when a person presses Send.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from read_scans import Vertex  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA_JSON = HERE / "data.json"
OUT = HERE / "actions.json"
DRAFTS = ROOT / "data" / "extracted" / "drafts"
SENDER_NAME = os.environ.get("SENDER_NAME", "Procurement Operations")
SENDER_ORG = os.environ.get("SENDER_ORG", "Soony Interactive GmbH")

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "assessment": {"type": "STRING", "description": "One or two sentences: what is unresolved and why it matters for the launch."},
        "emails": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {
                "title": {"type": "STRING", "description": "Short imperative label for the action, in English, max 9 words."},
                "recipient_type": {"type": "STRING", "enum": ["supplier", "internal"]},
                "recipient_name": {"type": "STRING"},
                "recipient_role": {"type": "STRING", "description": "Role or company of the recipient."},
                "to_email": {"type": "STRING", "description": "Only an address that appears in the context. Empty if none is given."},
                "language": {"type": "STRING", "description": "ISO 639-1 code of the email language."},
                "subject": {"type": "STRING"},
                "body": {"type": "STRING", "description": "Plain-text email in the recipient's language."},
                "body_english": {"type": "STRING", "description": "Faithful English version of the body. Same as body if written in English."},
                "ask": {"type": "STRING", "description": "The concrete answer or action we need back, in English, one sentence."},
                "reply_by": {"type": "STRING", "description": "When we need the answer, e.g. 'Sat 21 Nov 18:00 CET'."},
                "why_this_recipient": {"type": "STRING"},
            },
            "required": ["title", "recipient_type", "recipient_name", "to_email", "language", "subject", "body", "body_english", "ask"],
        }},
        "no_email_reason": {"type": "STRING", "description": "If no email is needed, why."},
    },
    "required": ["assessment", "emails"],
}

PROMPT = """You work in procurement operations for {org}. A game launch is at risk and you reconcile
what the ERP system says with what documents and suppliers say. For the case below, decide which
emails have to go out NOW to get the facts confirmed or the problem fixed, and draft them.

Rules
- Use only facts from the context. Never invent quantities, dates, names, prices or email addresses.
- Reconciliation comes first: when two sources disagree (system vs paper, our records vs the supplier's),
  one email must ask the party who knows to confirm the true figure or status, quoting both values and
  the document numbers. A request for a fix (replacement stock, express shipment) can go in the same
  email to the same recipient.
- Zero, one or two emails. Send none if an email would not change anything before the launch or the
  case is only informational: then explain in `no_email_reason`.
- Pick the recipient who can actually confirm or act: the supplier's contact for facts about what was
  shipped, produced or can still be shipped; an internal person (from the organisation chart and policy)
  for decisions, sign-offs and corrections in the system.
- Supplier emails: use the contact's address from the supplier directory and write in their preferred
  language. Internal emails: write in English; internal addresses are not in the data, so leave
  `to_email` empty and name the person and role.
- Be specific and short: quote document, PO, delivery-note, goods-receipt and shipment numbers, state
  what we see and what we need, and ask for a concrete reply by a concrete time before the launch.
- When asking a supplier to confirm a fact, ask an open question. Do not put the answer in their mouth.
- Polite, direct, no filler. Plain text, no markdown. Sign as:
  {sender}
  {org}

Now: {now}. Launch: {launch} (trucks leave Hamburg; nothing can be packed after that).
Pack-out shifts: Saturday 06:00-22:00 and Sunday 06:00-20:00.

CASE
{case}

CONTEXT
{context}
"""


def load() -> dict:
    if not DATA_JSON.exists():
        sys.exit("explorer/data.json missing: run python3 explorer/build.py first")
    return json.loads(DATA_JSON.read_text(encoding="utf-8"))


def case_key(flag: dict) -> str:
    if flag.get("material_id"):
        return "part:" + flag["material_id"]
    return "topic:" + re.sub(r"[^a-z0-9]+", "-", flag["title"].lower()).strip("-")[:60]


def build_cases(D: dict) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for f in D["flags"]:
        groups.setdefault(case_key(f), []).append(f)
    sev_rank = {"critical": 0, "warning": 1, "info": 2}
    cases = []
    cov = {c["component_id"]: c for c in D["coverage"]}
    for key, flags in groups.items():
        mat = flags[0].get("material_id")
        c = cov.get(mat)
        sev = min((f["severity"] for f in flags), key=lambda s: sev_rank[s])
        refs = sorted({r for f in flags for r in f["refs"]})
        truth = None
        if c:
            usable = c["adjusted"] + c["inbound_before_launch"]
            truth = {
                "label": c["description"], "unit": "pcs", "needed": c["needed"],
                "system": c["erp_stock"], "evidence": c["adjusted"], "not_usable": c["blocked"] + c["inflated"],
                "inbound_before_launch": c["inbound_before_launch"], "balance": usable - c["needed"],
                "fitted_by_supplier": c["fitted_by_supplier"],
            }
        name = c["description"] if c else flags[0]["title"]
        cases.append({"key": key, "material_id": mat, "name": name, "severity": sev, "findings": flags,
                      "refs": refs, "truth": truth,
                      "impact": max((f.get("qty") or 0) for f in flags)})
    cases.sort(key=lambda c: (sev_rank[c["severity"]], -c["impact"]))
    return cases


def context_for(case: dict, D: dict) -> str:
    """Everything the model may need for this case, as compact text."""
    mat = case["material_id"]
    out = []
    sup_ids = set()
    if mat:
        c = next((x for x in D["coverage"] if x["component_id"] == mat), None)
        if c:
            sup_ids |= {s["supplier_id"] for s in c["suppliers"]}
            out.append("PART " + json.dumps({k: c[k] for k in ("component_id", "description", "needed", "erp_stock", "blocked", "inflated",
                                                               "adjusted", "inbound_before_launch", "inbound_after_launch", "inbound", "batches",
                                                               "fitted_by_supplier")}, ensure_ascii=False))
            out.append("USED IN " + json.dumps(c["per"]) + " | REMAINING TO PACK " + json.dumps(
                {k: {"edition": v["edition"], "to_pack": v["to_pack"]} for k, v in D["remaining"].items()}))
        grs = [g for g in D["goods_receipts"] if g["material_id"] == mat][-6:]
        out.append("RECENT GOODS RECEIPTS " + json.dumps(grs, ensure_ascii=False))
        sup_ids |= {g["supplier_id"] for g in grs}
        open_pos = [p for p in D["purchase_orders"] if p["material_id"] == mat and p["status"] in ("open", "awaiting_approval")][:8]
        out.append("OPEN PO LINES " + json.dumps(open_pos, ensure_ascii=False))
        ships = [s for s in D["shipments"] if mat in s["material_ids"].split("|")]
        out.append("SHIPMENTS " + json.dumps([{k: s[k] for k in ("shipment_id", "carrier_id", "mode", "reference", "supplier_id", "po_numbers", "origin",
                                                                  "destination", "etd", "eta", "eta_dc", "before_launch", "status", "updated_at", "note")}
                                              for s in ships], ensure_ascii=False))
    text = " ".join(f["title"] + " " + f["detail"] for f in case["findings"])
    for sid, s in D["suppliers"].items():
        if sid in text or s["name"] in text:
            sup_ids.add(sid)
    for ref in case["refs"]:
        d = next((x for x in D["documents"] if x["path"] == ref), None)
        if not d:
            continue
        if d.get("supplier_id"):
            sup_ids.add(d["supplier_id"])
        body = json.dumps({k: v for k, v in d["read"].items() if k not in ("model", "read_at")}, ensure_ascii=False) if d.get("read") else d.get("text", "")
        out.append(f"DOCUMENT {d['name']} ({d['kind']}): {body[:3000]}")
    for sid in sorted(sup_ids):
        s = D["suppliers"].get(sid)
        if not s:
            continue
        out.append("SUPPLIER " + json.dumps({k: s.get(k) for k in ("supplier_id", "name", "legal_name", "country", "city", "contact_name", "contact_email",
                                                                    "preferred_language", "incoterm", "qualification_status", "supplier_since",
                                                                    "conditional_expires", "notes", "components")}, ensure_ascii=False))
        for d in D["documents"]:
            if d.get("supplier_id") != sid:
                continue
            if d["kind"] == "contracts" and d.get("read"):
                out.append(f"CONTRACT {d['name']}: " + json.dumps(d["read"].get("key_terms"), ensure_ascii=False))
            elif d["kind"] == "contracts" and d.get("text"):
                out.append(f"CONTRACT {d['name']}: {d['text'][:3500]}")
            elif d["kind"] == "notices" and d.get("text"):
                out.append(f"SUPPLIER NOTICE {d['name']}: {d['text'][:2500]}")
    for d in D["documents"]:
        if d["kind"] == "context" and d.get("text"):
            out.append(f"INTERNAL {d['name']}: {d['text'][:3500]}")
    out.append("CARRIERS " + json.dumps(D["master"].get("logistics_providers", []), ensure_ascii=False))
    return "\n".join(out)


def main() -> None:
    force = "--force" in sys.argv
    D = load()
    cases = build_cases(D)
    DRAFTS.mkdir(parents=True, exist_ok=True)
    supplier_emails = {s["contact_email"].lower(): sid for sid, s in D["suppliers"].items() if s.get("contact_email")}
    now = os.environ.get("NOW") or D["generated_at"][:16].replace("T", " ")
    launch = D["launch"].replace("T", " ")[:16]
    vx = None
    jobs = []
    for case in cases:
        case_text = json.dumps({"name": case["name"], "severity": case["severity"], "findings": [
            {k: f[k] for k in ("severity", "category", "title", "detail")} for f in case["findings"]], "numbers": case["truth"]}, ensure_ascii=False)
        prompt = PROMPT.format(org=SENDER_ORG, sender=SENDER_NAME, now=now, launch=launch, case=case_text, context=context_for(case, D))
        # the cache key ignores the clock so a rebuild a few minutes later does not re-draft everything
        digest = hashlib.sha256(re.sub(r"Now: .*?\. Launch", "Now. Launch", prompt).encode()).hexdigest()[:24]
        jobs.append((case, prompt, DRAFTS / f"{digest}.json"))
    todo = [j for j in jobs if force or not j[2].exists()]
    print(f"{len(cases)} cases, {len(todo)} to plan and draft")
    if todo:
        vx = Vertex()

        def work(job):
            case, prompt, cache = job
            try:
                cache.write_text(json.dumps(vx.ask(prompt, SCHEMA), ensure_ascii=False, indent=1), encoding="utf-8")
                return f"ok    {case['name']}"
            except Exception as e:
                return f"FAIL  {case['name']}: {e}"
        with ThreadPoolExecutor(max_workers=6) as pool:
            for line in pool.map(work, todo):
                print(line, flush=True)

    actions, quiet = [], []
    for case, _, cache in jobs:
        if not cache.exists():
            continue
        plan = json.loads(cache.read_text(encoding="utf-8"))
        base = {"case": case["key"], "case_name": case["name"], "severity": case["severity"], "material_id": case["material_id"],
                "impact": case["impact"], "assessment": plan.get("assessment", ""), "truth": case["truth"],
                "findings": [{k: f[k] for k in ("severity", "category", "title", "detail", "refs")} for f in case["findings"]],
                "evidence": case["refs"]}
        if not plan.get("emails"):
            quiet.append({**base, "no_email_reason": plan.get("no_email_reason", "")})
            continue
        for i, e in enumerate(plan["emails"]):
            to = (e.get("to_email") or "").strip()
            known = supplier_emails.get(to.lower())
            if e["recipient_type"] == "supplier" and not known:
                to = ""   # never send to an address the data does not contain
            aid = hashlib.sha256(f"{case['key']}|{e['recipient_type']}|{e['recipient_name']}|{i}".encode()).hexdigest()[:12]
            actions.append({**base, "id": aid, "title": e["title"], "recipient_type": e["recipient_type"],
                            "recipient_name": e["recipient_name"], "recipient_role": e.get("recipient_role", ""),
                            "supplier_id": known, "to": to, "cc": "", "language": e.get("language", "en"),
                            "subject": e["subject"], "body": e["body"], "body_english": e.get("body_english", ""),
                            "ask": e["ask"], "reply_by": e.get("reply_by", ""), "why_this_recipient": e.get("why_this_recipient", "")})
    OUT.write_text(json.dumps({"generated_at": D["generated_at"], "actions": actions, "no_action": quiet}, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(actions)} emails drafted, {len(quiet)} cases need no email")


if __name__ == "__main__":
    main()

import asyncio
import json

import pytest

from faro import files
from faro.agent import AgentRunner, watch_folder
from faro.hub import Hub
from faro.scripted import ScriptedModel


async def until(condition, timeout=5.0):
    for _ in range(int(timeout / 0.02)):
        if condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met in time")


@pytest.fixture
def folder(tmp_path):
    data = tmp_path / "data"
    (data / "context").mkdir(parents=True)
    (data / "context" / "notes.md").write_text("Order 4500318768: 8000 art books.\n")
    (data / "erp.csv").write_text("po,qty\n4500318768,80000\n")
    return data


def test_read_stays_inside_the_folder(folder):
    with pytest.raises(files.FileError):
        files.read(folder, "../secret.txt")
    assert "8000 art books" in files.read(folder, "context/notes.md")
    assert "erp.csv:2" in files.search_files(folder, "4500318768")


def test_long_files_are_paged_not_cut(folder):
    (folder / "big.txt").write_text("x" * (files.PAGE_CHARS + 10))
    first = files.read(folder, "big.txt")
    assert f"offset={files.PAGE_CHARS}" in first
    assert files.read(folder, "big.txt", offset=files.PAGE_CHARS) == "x" * 10


async def test_agent_reads_proposes_and_hears_the_decision(folder, tmp_path):
    hub = Hub(folder, tmp_path / "state")
    tasks = [asyncio.create_task(watch_folder(hub, 0.05)), asyncio.create_task(AgentRunner(hub, ScriptedModel()).run_forever())]
    try:
        await until(lambda: hub.approvals)
        approval = hub.approvals["A-1"]
        assert approval.tool == "send_email" and approval.status == "pending"
        assert approval.evidence == ["context/notes.md"]
        thought = next(e for e in hub.events if e["kind"] == "thought")
        assert len(thought["label"]) <= 150 < len(thought["text"])  # shown short, full text kept
        assert any(e["kind"] == "step" and "Reading the first document" in e["label"] for e in hub.events)
        assert not (tmp_path / "state" / "actions.jsonl").exists()  # nothing happens before a person approves

        await hub.decide("A-1", approved=True, note="ok")
        await until(lambda: any(e["kind"] == "agent" and "decision noted" in e["text"] for e in hub.events))
        logged = json.loads((tmp_path / "state" / "actions.jsonl").read_text())
        assert logged["id"] == "A-1" and logged["status"] == "approved" and logged["outcome"] == "recorded"

        hub.chat("are we fine?")
        await until(lambda: any(e["kind"] == "agent" and "are we fine?" in e["text"] for e in hub.events))

        (folder / "late_notice.txt").write_text("Truck delayed.")
        await until(lambda: any(e["kind"] == "files" and e["label"] == "1 new" and "late_notice.txt" in e["text"] for e in hub.events))
        await until(lambda: any(e["kind"] == "agent" and "noted the change" in e["text"] for e in hub.events))
    finally:
        for task in tasks:
            task.cancel()


async def test_rejection_is_not_logged_and_cannot_be_decided_twice(folder, tmp_path):
    hub = Hub(folder, tmp_path / "state")
    hub.propose("update_record", {"system": "SAP", "record": "x", "changes": {"qty": "8000"}}, "h", "r", [], "risk")
    await hub.decide("A-1", approved=False, note="wrong batch")
    assert "REJECTED" in hub.inbox[-1] and "wrong batch" in hub.inbox[-1]
    assert not (tmp_path / "state" / "actions.jsonl").exists()
    with pytest.raises(ValueError):
        await hub.decide("A-1", approved=True)


def test_any_text_encoding_and_excel_open(folder):
    (folder / "latin.csv").write_bytes("Lieferant;Menge\nMüller;8000\n".encode("cp1252"))
    assert "Müller;8000" in files.read(folder, "latin.csv")
    from openpyxl import Workbook

    book = Workbook()
    book.active.title = "Plan"
    book.active.append(["part", "qty"])
    book.active.append(["art book", 8000])
    book.save(folder / "plan.xlsx")
    assert "## Sheet: Plan" in files.read(folder, "plan.xlsx") and "art book | 8000" in files.read(folder, "plan.xlsx")
    assert "plan.xlsx:3" in files.search_files(folder, "art book")  # spreadsheets are searchable
    (folder / "blob.bin").write_bytes(bytes(range(256)) * 20)
    with pytest.raises(files.FileError, match="binary"):
        files.read(folder, "blob.bin")


def test_scanned_and_mixed_pdfs_come_back_page_by_page(folder):
    import pymupdf as fitz

    scan = fitz.open()
    scan.new_page().draw_rect(fitz.Rect(50, 50, 300, 300), fill=(0, 0, 0))  # a page with no text layer
    text_page = scan.new_page()
    text_page.insert_text((72, 72), "Delivery note WZ-1: 8000 pieces received and counted at the dock.")
    for _ in range(files.SCAN_PAGES + 1):
        scan.new_page().draw_rect(fitz.Rect(10, 10, 60, 60), fill=(0, 0, 0))
    scan.save(folder / "mixed.pdf")

    blocks = files.read(folder, "mixed.pdf")
    images = [b for b in blocks if b["type"] == "image"]
    assert len(images) == files.SCAN_PAGES and images[0]["mime_type"] == "image/jpeg"
    assert any("8000 pieces" in b.get("text", "") for b in blocks)
    assert "offset=5" in blocks[-1]["text"]  # the rest is offered, not dropped
    rest = files.read(folder, "mixed.pdf", offset=5)
    assert len([b for b in rest if b["type"] == "image"]) == 2
    assert "mixed.pdf" in files.search_files(folder, "WZ-1")  # text pages of a PDF are searchable


def test_large_and_unusual_images_are_converted(folder):
    import base64

    import pymupdf as fitz

    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 5000, 3000), False)
    pixmap.clear_with(200)
    pixmap.save(folder / "huge.png")
    block = files.read(folder, "huge.png")[1]
    assert block["mime_type"] == "image/jpeg"
    shrunk = fitz.Pixmap(base64.b64decode(block["base64"]))
    assert max(shrunk.width, shrunk.height) <= files.MAX_SIDE


async def test_history_is_summarised_when_it_grows(folder, tmp_path, monkeypatch):
    from faro import config

    monkeypatch.setattr(config, "COMPACT_TOKENS", 200)
    hub = Hub(folder, tmp_path / "state")
    runner = AgentRunner(hub, ScriptedModel())
    task = asyncio.create_task(runner.run_forever())
    try:
        for i in range(30):
            hub.chat(f"question {i} " + "padding " * 30)
            await until(lambda i=i: any(e["kind"] == "agent" and f"question {i} " in e["text"] for e in hub.events))
        state = await runner.agent.aget_state(runner.config)
        assert len(state.values["messages"]) < 40  # 60 messages went in; old ones were folded into a summary
        assert not any(e["kind"] == "error" for e in hub.events)
    finally:
        task.cancel()


def fake_mail_service(sent, inbox_messages):
    import httpx

    def handle(request):
        assert request.headers["Authorization"] == "Bearer test-key"
        path = request.url.path
        if request.method == "POST" and path.endswith("/messages/send"):
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"message_id": "<m1>", "thread_id": "t1"})
        if request.method == "POST" and path.endswith("/reply"):
            sent.append({"reply_path": request.url.raw_path.decode(), **json.loads(request.content)})
            return httpx.Response(200, json={"message_id": "<m2>", "thread_id": "t1"})
        if path.endswith("/messages"):
            return httpx.Response(200, json={"messages": list(inbox_messages)})
        for m in inbox_messages:
            if path.endswith("/messages/" + m["message_id"]):
                return httpx.Response(200, json=m)
        return httpx.Response(500, text="mail service down")

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


async def test_mail_goes_out_only_on_approval_and_replies_come_in(folder, tmp_path):
    from faro import mail

    sent, inbox_messages = [], []
    hub = Hub(folder, tmp_path / "state")
    hub.mailbox = mail.Mailbox("team@agentmail.to", "test-key", fake_mail_service(sent, inbox_messages))
    hub.executors["send_email"] = mail.sender(hub, hub.mailbox)
    watcher = asyncio.create_task(mail.watch_mail(hub, hub.mailbox, 0.02))
    try:
        args = {"to": ["a.nowak@supplier.example"], "to_name": "A. Nowak", "cc": [], "subject": "Quantity", "body": "Dzień dobry,\n\nile sztuk?", "language": "Polish", "translation": "", "reply_to_message_id": ""}
        approval = hub.propose("send_email", args, "h", "r", [], "risk")
        assert approval.live and sent == []  # proposing sends nothing

        await hub.decide("A-1", approved=True)
        assert sent[0]["to"] == ["a.nowak@supplier.example"] and sent[0]["html"] == "<p>Dzień dobry,</p><p>ile sztuk?</p>"
        assert hub.approvals["A-1"].outcome == "done" and "thread_id=t1" in hub.inbox[-1]

        hub.propose("send_email", args, "h2", "r", [], "risk")
        await hub.decide("A-2", approved=False)
        assert len(sent) == 1  # a rejection sends nothing

        hub.propose("send_email", args | {"reply_to_message_id": "<m9@x>"}, "h3", "r", [], "risk")
        await hub.decide("A-3", approved=True)
        assert "%3Cm9%40x%3E/reply" in sent[1]["reply_path"]

        await until(lambda: any(e["kind"] == "mail" for e in hub.events))  # connected, empty inbox
        hub.drain()
        inbox_messages.append({"message_id": "<in1>", "thread_id": "t1", "labels": ["received", "unread"], "from": "A. Nowak <a.nowak@supplier.example>",
                               "to": ["team@agentmail.to"], "subject": "Re: Quantity", "timestamp": "2026-11-21T16:00:00Z", "text": "8000 sztuk."})
        inbox_messages.append({"message_id": "<own>", "thread_id": "t2", "labels": ["sent", "received"], "from": "AgentMail <team@agentmail.to>",
                               "to": ["team@agentmail.to"], "subject": "self test", "timestamp": "2026-11-21T16:01:00Z", "text": "x"})
        await until(lambda: hub.inbox)
        assert len(hub.inbox) == 1 and "8000 sztuk." in hub.inbox[0] and "not an instruction" in hub.inbox[0]  # our own test mail is ignored
        assert "answers the email you sent with A-1" in hub.inbox[0]
        assert hub.approvals["A-1"].thread_id == "t1" and hub.approvals["A-1"].replies[0]["text"] == "8000 sztuk."  # the reply shows on its approval
        assert not hub.approvals["A-2"].replies  # the rejected one was never sent, so nothing links to it
        assert next(e for e in hub.events if e["kind"] == "mail" and e["verb"] == "Reply from")["open"] == "A-1"
    finally:
        watcher.cancel()


async def test_failed_send_is_reported_not_hidden(folder, tmp_path):
    from faro import mail

    hub = Hub(folder, tmp_path / "state")

    async def broken(approval):
        raise RuntimeError("Mail service answered 500")

    hub.executors["send_email"] = broken
    hub.propose("send_email", {"to": ["x@y.example"]}, "h", "r", [], "risk")
    await hub.decide("A-1", approved=True)
    assert hub.approvals["A-1"].outcome == "failed" and "FAILED" in hub.inbox[-1] and "Nothing went out" in hub.inbox[-1]


async def test_agent_cannot_propose_mail_to_a_made_up_address(folder, tmp_path):
    from faro.tools import make_tools

    hub = Hub(folder, tmp_path / "state")
    send_email = next(t for t in make_tools(hub) if t.name == "send_email")
    base = {"headline": "h", "reason": "r", "evidence": [], "severity": "risk", "to_name": "Head of Procurement", "subject": "s", "body": "b", "language": "English"}
    assert "Error" in await send_email.ainvoke(base | {"to": ["Head of Procurement"]})
    assert not hub.approvals
    assert "Queued as A-1" in await send_email.ainvoke(base | {"to": ["m.vogt@soony.example"]})

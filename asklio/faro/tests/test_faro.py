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
        approval, issue = hub.approvals["A-1"], hub.issues["I-1"]
        assert approval.tool == "send_email" and approval.status == "pending" and approval.issue_id == "I-1"
        assert issue.evidence == ["context/notes.md"]
        assert [h["kind"] for h in issue.history] == ["found", "proposed"] and issue.history[1]["ref"] == "A-1"
        thought = next(e for e in hub.events if e["kind"] == "thought")
        assert len(thought["label"]) <= 150 < len(thought["text"])  # shown short, full text kept
        assert any(e["kind"] == "step" and "Reading the first document" in e["label"] for e in hub.events)
        assert approval.outcome == ""  # nothing happens before a person approves

        await hub.decide("A-1", approved=True, note="ok")
        await until(lambda: any(e["kind"] == "agent" and "decision noted" in e["text"] for e in hub.events))
        logged = Hub(folder, tmp_path / "state").approvals["A-1"]  # read back from the database
        assert logged.status == "approved" and logged.outcome == "recorded"
        assert hub.issues["I-1"].history[-1]["kind"] == "approved"  # the decision is part of the issue's history

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
    hub.propose("update_record", {"system": "SAP", "record": "x", "changes": [{"field": "qty", "old_value": "80000", "new_value": "8000"}]}, hub.open_issue("h", "risk", "s", []).id, "h", "r")
    await hub.decide("A-1", approved=False, note="wrong batch")
    assert "REJECTED" in hub.inbox[-1] and "wrong batch" in hub.inbox[-1]
    assert Hub(folder, tmp_path / "state").approvals["A-1"].status == "rejected" and not hub.store.corrections()
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
        args = {"to": ["a.nowak@supplier.example"], "to_name": "A. Nowak", "cc": [], "subject": "Quantity", "body": "Dzień dobry,\n\nile sztuk?", "language": "Polish", "translation": "", "reply_to_message_id": "", "brief": "ask the quantity"}
        approval = hub.propose("send_email", args, hub.open_issue("h", "risk", "s", []).id, "h", "r")
        assert approval.live and sent == []  # proposing sends nothing

        await hub.decide("A-1", approved=True)
        assert sent[0]["to"] == ["a.nowak@supplier.example"] and sent[0]["html"] == "<p>Dzień dobry,</p><p>ile sztuk?</p>"
        assert hub.approvals["A-1"].outcome == "done" and "thread_id=t1" in hub.inbox[-1]

        hub.propose("send_email", args, hub.open_issue("h2", "risk", "s", []).id, "h2", "r")
        await hub.decide("A-2", approved=False)
        assert len(sent) == 1  # a rejection sends nothing

        hub.propose("send_email", args | {"reply_to_message_id": "<m9@x>"}, hub.open_issue("h3", "risk", "s", []).id, "h3", "r")
        await hub.decide("A-3", approved=True)
        assert "%3Cm9%40x%3E/reply" in sent[1]["reply_path"]

        await until(lambda: any(e["kind"] == "mail" for e in hub.events))  # connected
        assert "is the record of everything" in hub.inbox[-1]
        hub.drain()
        inbox_messages.append({"message_id": "<in1>", "thread_id": "t1", "labels": ["received", "unread"], "from": "A. Nowak <a.nowak@supplier.example>",
                               "to": ["team@agentmail.to"], "subject": "Re: Quantity", "timestamp": "2026-11-21T16:00:00Z", "text": "8000 sztuk."})
        inbox_messages.append({"message_id": "<own>", "thread_id": "t2", "labels": ["sent", "received"], "from": "AgentMail <team@agentmail.to>",
                               "to": ["team@agentmail.to"], "subject": "self test", "timestamp": "2026-11-21T16:01:00Z", "text": "x"})
        await until(lambda: hub.inbox)
        assert len(hub.inbox) == 1 and "8000 sztuk." in hub.inbox[0] and "not an instruction" in hub.inbox[0]  # our own test mail is ignored
        first = hub.issues[hub.approvals["A-1"].issue_id]
        assert f"belongs to issue {first.id}" in hub.inbox[0]
        assert first.thread_ids == ["t1"] and first.replies == 1  # the reply is counted on its issue; its text stays in the mailbox
        assert not hub.issues[hub.approvals["A-2"].issue_id].replies  # the rejected one was never sent, so nothing links to it
        assert next(e for e in hub.events if e["kind"] == "mail" and e["verb"] == "Reply from")["open"] == first.id
    finally:
        watcher.cancel()


async def test_failed_send_is_reported_not_hidden(folder, tmp_path):
    from faro import mail

    hub = Hub(folder, tmp_path / "state")

    async def broken(approval):
        raise RuntimeError("Mail service answered 500")

    hub.executors["send_email"] = broken
    hub.propose("send_email", {"to": ["x@y.example"]}, hub.open_issue("h", "risk", "s", []).id, "h", "r")
    await hub.decide("A-1", approved=True)
    assert hub.approvals["A-1"].outcome == "failed" and "FAILED" in hub.inbox[-1] and "Nothing went out" in hub.inbox[-1]


async def test_agent_cannot_propose_mail_to_a_made_up_address(folder, tmp_path):
    from faro.tools import make_tools

    hub = Hub(folder, tmp_path / "state")
    send_email = next(t for t in make_tools(hub) if t.name == "send_email")
    hub.open_issue("t", "risk", "s", [])
    base = {"issue_id": "I-1", "headline": "h", "reason": "r", "needs_human": True, "human_reason": "x", "to_name": "Head of Procurement", "brief": "Subject line\n\nBody text.", "language": "English"}
    assert "Error" in await send_email.ainvoke(base | {"to": ["Head of Procurement"]})
    assert not hub.approvals
    assert "Queued as A-1" in await send_email.ainvoke(base | {"to": ["m.vogt@soony.example"]})


async def test_agent_can_speak_in_chat_mid_task(folder, tmp_path):
    from faro.tools import make_tools

    hub = Hub(folder, tmp_path / "state")
    tell_team = next(t for t in make_tools(hub) if t.name == "tell_team")
    await tell_team.ainvoke({"message": " Statues are 3,400 short. "})
    assert hub.events[-1]["kind"] == "agent" and hub.events[-1]["text"] == "Statues are 3,400 short."


async def test_email_is_drafted_by_the_mail_model_and_checked_against_the_mailbox(folder, tmp_path):
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda

    from faro import mail
    from faro.tools import make_tools

    seen = []

    def fake_sonnet(messages):
        seen.append(messages)
        return AIMessage("SUBJECT: Potwierdzenie ilości\nBODY:\nDzień dobry,\n\nile sztuk wysłano?\nENGLISH:\nHello,\n\nhow many pieces were shipped?")

    earlier = {"message_id": "<old>", "thread_id": "t0", "labels": ["sent"], "from": "Team <team@agentmail.to>", "to": ["a.nowak@supplier.example"],
               "subject": "First question", "timestamp": "2026-11-21T10:00:00Z", "text": "..."}
    hub = Hub(folder, tmp_path / "state")
    hub.mailbox = mail.Mailbox("team@agentmail.to", "test-key", fake_mail_service([], [earlier]))
    hub.write_email = mail.writer(RunnableLambda(fake_sonnet), "We are the procurement team.")
    send_email = next(t for t in make_tools(hub) if t.name == "send_email")
    hub.open_issue("t", "risk", "s", [])
    result = await send_email.ainvoke({"issue_id": "I-1", "headline": "h", "reason": "r", "needs_human": True, "human_reason": "x", "to": ["a.nowak@supplier.example"],
                                       "to_name": "A. Nowak, Karton Nowak", "language": "Polish", "brief": "Ask how many pieces were shipped on WZ-1."})
    args = hub.approvals["A-1"].args
    assert args["subject"] == "Potwierdzenie ilości" and args["body"].startswith("Dzień dobry") and args["translation"].startswith("Hello")
    assert "Polish" in seen[0][0][1] and "WZ-1" in seen[0][1][1]  # the writer got the language and the brief
    assert args["earlier"] == [{"ts": "2026-11-21T10:00:00Z", "direction": "sent", "subject": "First question", "thread_id": "t0"}]
    assert "already holds 1 message" in result  # the agent is told what the mailbox says


async def test_one_slow_mailbox_answer_is_not_an_alarm(folder, tmp_path):
    from faro import mail

    class Flaky:
        inbox = "team@agentmail.to"
        calls = 0

        async def messages(self, limit=30, labels=None):
            self.calls += 1
            if self.calls in (2, 4, 5, 6):
                raise TimeoutError()
            return []

        def is_own(self, message):
            return False

    hub, box = Hub(folder, tmp_path / "state"), Flaky()
    watcher = asyncio.create_task(mail.watch_mail(hub, box, 0.01))
    try:
        await until(lambda: box.calls >= 3)
        assert not any(e["kind"] == "error" for e in hub.events)  # a single miss stays quiet
        await until(lambda: box.calls >= 8)
        errors = [e for e in hub.events if e["kind"] == "error"]
        assert len(errors) == 1 and "three times in a row" in errors[0]["text"] and "TimeoutError" in errors[0]["text"]
        assert any(e["kind"] == "mail" and e["label"] == "reachable again" for e in hub.events)
    finally:
        watcher.cancel()


def test_files_can_be_looked_at_in_the_browser(folder):
    import pymupdf as fitz

    (folder / "semi.csv").write_text("po;qty\n4500318768;8000\n")
    table = files.preview(folder, "semi.csv")["tables"][0]
    assert table["rows"] == [["po", "qty"], ["4500318768", "8000"]]  # the delimiter is detected
    doc = fitz.open()
    doc.new_page(); doc.new_page()
    doc.save(folder / "two.pdf")
    assert files.preview(folder, "two.pdf") == {"kind": "pages", "pages": 2}
    assert files.page_image(folder, "two.pdf", 1)[:3] == b"\xff\xd8\xff"  # a JPEG
    with pytest.raises(files.FileError):
        files.page_image(folder, "two.pdf", 2)
    assert files.preview(folder, "context/notes.md")["kind"] == "text"
    with pytest.raises(files.FileError):
        files.preview(folder, "../outside.txt")


async def test_approvals_survive_a_restart_and_the_agent_is_told(folder, tmp_path):
    hub = Hub(folder, tmp_path / "state")
    hub.propose("update_record", {"system": "SAP", "record": "x", "changes": [{"field": "qty", "old_value": "80000", "new_value": "8000"}]}, hub.open_issue("Receipt overstated", "blocker", "s", []).id, "Receipt overstated", "r")
    await hub.decide("A-1", approved=True)

    again = Hub(folder, tmp_path / "state")  # a new process
    assert again.restored and again.approvals["A-1"].outcome == "recorded" and len(again.events) == len(hub.events)
    assert [h["kind"] for h in again.issues["I-1"].history] == ["found", "proposed", "approved"]
    watcher = asyncio.create_task(watch_folder(again, 0.05))
    try:
        await until(lambda: again.inbox)
        assert "Do not open or propose these again" in again.inbox[0] and "I-1 [open, blocker] Receipt overstated" in again.inbox[0] and "A-1 [approved, recorded] update_record: Receipt overstated" in again.inbox[0]
    finally:
        watcher.cancel()
    assert again.open_issue("second", "info", "s", []).id == "I-2"  # numbering continues
    assert again.propose("edit_file", {}, "I-2", "h", "r").id == "A-2"


async def test_each_message_is_translated_once_and_remembered(folder, tmp_path):
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda

    from faro import mail

    calls = []

    def fake_sonnet(messages):
        calls.append(messages[1][1])
        return AIMessage("LANGUAGE: English\nSUMMARY: Asks how many.\nENGLISH:\nSAME" if "Hello" in messages[1][1] else "LANGUAGE: Polish\nSUMMARY: They hold 8,000 pieces.\nENGLISH:\nWe have 8,000 pieces in stock.")

    cache = {}
    inbox_messages = [
        {"message_id": "<pl>", "thread_id": "t1", "labels": ["received"], "from": "A. Nowak <a.nowak@supplier.example>", "to": ["team@agentmail.to"], "timestamp": "2026-11-21T16:39:00Z", "text": "Mamy 8 000 szt."},
        {"message_id": "<en>", "thread_id": "t1", "labels": ["sent"], "from": "Team <team@agentmail.to>", "to": ["a.nowak@supplier.example"], "timestamp": "2026-11-21T16:35:00Z", "text": "Hello, how many?"},
    ]
    import httpx

    def handle(request):
        return httpx.Response(200, json={"thread_id": "t1", "subject": "Quantity", "messages": inbox_messages})

    hub = Hub(folder, tmp_path / "state")
    box = mail.Mailbox("team@agentmail.to", "k", httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    hub.translate_mail = mail.translator(RunnableLambda(fake_sonnet), cache)
    view = await mail.thread_view(hub, box, "t1")
    received, sent = view["messages"]
    assert received["direction"] == "received" and received["language"] == "Polish" and received["english"] == "We have 8,000 pieces in stock." and received["summary"] == "They hold 8,000 pieces."
    assert sent["direction"] == "sent" and sent["english"] == ""  # already English: no second tab
    await mail.thread_view(hub, box, "t1")
    assert len(calls) == 2  # the second look cost nothing
    hub.translate_mail = mail.translator(RunnableLambda(fake_sonnet), cache)  # after a restart
    await mail.thread_view(hub, box, "t1")
    assert len(calls) == 2


async def test_an_issue_carries_its_whole_story(folder, tmp_path):
    from faro.tools import make_tools

    hub = Hub(folder, tmp_path / "state")
    tools = {t.name: t for t in make_tools(hub)}
    assert "Opened as I-1" in await tools["open_issue"].ainvoke({"title": "Art books 5,900 short", "severity": "blocker", "summary": "Receipt overstated.", "evidence": ["erp.csv"]})
    assert "no issue 'I-9'" in await tools["update_record"].ainvoke({"issue_id": "I-9", "headline": "h", "reason": "r", "needs_human": True, "human_reason": "x", "system": "SAP", "record": "x", "changes": [{"field": "qty", "old_value": "80000", "new_value": "8000"}]})
    await tools["update_record"].ainvoke({"issue_id": "I-1", "headline": "Correct the receipt", "reason": "r", "needs_human": True, "human_reason": "x", "system": "SAP", "record": "x", "changes": [{"field": "qty", "old_value": "80000", "new_value": "8000"}]})
    await hub.decide("A-1", approved=False, note="wrong batch")
    await tools["update_issue"].ainvoke({"issue_id": "I-1", "note": "Supplier confirmed 8,000.", "next_step": "Paul Winter must send the call-off", "thread_id": "t7", "evidence": ["context/notes.md"]})
    issue = hub.issues["I-1"]
    assert [h["kind"] for h in issue.history] == ["found", "proposed", "rejected", "note"]
    assert "wrong batch" in issue.history[2]["text"] and issue.next_step == "Paul Winter must send the call-off"
    assert issue.thread_ids == ["t7"] and issue.evidence == ["erp.csv", "context/notes.md"]
    await tools["update_issue"].ainvoke({"issue_id": "I-1", "note": "Books arrived.", "next_step": "none", "status": "resolved"})
    assert issue.status == "resolved" and issue.next_step == "" and issue.history[-1]["kind"] == "resolved"


async def test_history_merges_faro_entries_and_mail_in_time_order(folder, tmp_path):
    import httpx

    from faro import mail

    messages = [
        {"message_id": "<out>", "thread_id": "t1", "labels": ["sent"], "from": "Team <team@agentmail.to>", "to": ["a@supplier.example"], "timestamp": "2026-11-21T16:35:11.099Z", "text": "How many?"},
        {"message_id": "<in>", "thread_id": "t1", "labels": ["received"], "from": "A <a@supplier.example>", "to": ["team@agentmail.to"], "timestamp": "2026-11-21T16:39:03.000Z", "text": "8000."},
    ]
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"thread_id": "t1", "subject": "Quantity", "messages": messages})))
    hub = Hub(folder, tmp_path / "state")
    hub.mailbox = mail.Mailbox("team@agentmail.to", "k", client)
    issue = hub.open_issue("Art books short", "blocker", "s", [])
    issue.history[0]["ts"] = mail.epoch("2026-11-21T16:00:00Z")
    hub.update_issue("I-1", "Linked the conversation.", thread_id="t1")
    issue.history[1]["ts"] = mail.epoch("2026-11-21T16:37:00Z")

    result = await mail.issue_history(hub, issue)
    assert [e["kind"] for e in result["entries"]] == ["found", "mail_sent", "note", "mail_received"] and result["problem"] == ""
    assert all(isinstance(e["ts"], float) for e in result["entries"])
    json.dumps(result)  # what the endpoint returns must serialise

    broken = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500, text="down")))
    hub.mailbox = mail.Mailbox("team@agentmail.to", "k", broken)
    degraded = await mail.issue_history(hub, issue)
    assert [e["kind"] for e in degraded["entries"]] == ["found", "note"] and "could not be read" in degraded["problem"]


async def test_long_history_entries_get_a_cached_one_line_summary(folder, tmp_path):
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda

    from faro import mail

    calls = []

    def fake_sonnet(messages):
        calls.append(messages[1][1])
        return AIMessage("Receipt overstated by **72,000**.")

    hub = Hub(folder, tmp_path / "state")
    hub.summarize = mail.summarizer(RunnableLambda(fake_sonnet), hub.store.cache("summaries"))
    issue = hub.open_issue("Art books short", "blocker", "Goods receipt 5000413065 was booked as 80,000 art books although the delivery note was corrected by hand to 8,000, so stock is overstated by 72,000.", [])
    hub.update_issue("I-1", "Supplier confirmed.")
    first = (await mail.issue_history(hub, issue))["entries"]
    assert first[0]["summary"] == "Receipt overstated by **72,000**." and first[1]["summary"] == ""  # the short note is its own summary
    await mail.issue_history(hub, issue)
    assert len(calls) == 1


async def test_auto_mode_carries_out_only_what_the_agent_marked_routine(folder, tmp_path):
    sent = []

    async def send(approval):
        sent.append(approval.id)
        return "Sent."

    hub = Hub(folder, tmp_path / "state")
    hub.executors["send_email"] = send
    issue = hub.open_issue("Cards late", "risk", "s", [])
    waiting = hub.propose("send_email", {"to": ["a@x.example"]}, issue.id, "Ask for flight status", "r", needs_human=False, human_reason="Only a question.")
    await asyncio.sleep(0.05)
    assert waiting.status == "pending" and sent == []  # auto mode is off: nothing moves

    hub.set_auto(True)
    await until(lambda: waiting.status == "approved")
    assert sent == ["A-1"] and waiting.auto and issue.history[-1]["kind"] == "auto_sent"
    assert "automatically, under auto mode" in hub.inbox[-1]

    order = hub.propose("send_email", {"to": ["a@x.example"]}, issue.id, "Place the call-off", "r", needs_human=True, human_reason="Commits EUR 16,800.")
    routine = hub.propose("send_email", {"to": ["a@x.example"]}, issue.id, "Chase the answer", "r", needs_human=False, human_reason="A reminder.")
    await until(lambda: routine.status == "approved")
    assert order.status == "pending" and sent == ["A-1", "A-3"]  # the order still waits for a person

    again = Hub(folder, tmp_path / "state")
    assert again.auto and again.approvals["A-2"].needs_human  # the switch survives a restart
    hub.set_auto(False)
    late = hub.propose("send_email", {"to": ["a@x.example"]}, issue.id, "Another question", "r", needs_human=False, human_reason="q")
    await asyncio.sleep(0.05)
    assert late.status == "pending"


def test_proposals_from_before_auto_mode_stay_with_a_person(folder, tmp_path):
    from faro.hub import Approval

    assert Approval("A-1", "I-1", "send_email", {}, "h", "r").needs_human


async def test_emphasis_never_changes_the_words(folder, tmp_path):
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda

    from faro import mail

    text = "Stock is 19,300 against 25,200 needed. Paul Winter must send the call-off, Katrin Jansen must book a dock slot."
    good = "Stock is **19,300** against 25,200 needed.\n- **Paul Winter** must send the call-off,\n- Katrin Jansen must book a dock slot."
    answers = iter([good, "Stock is **19,300**, far too low. Someone must act."])
    emphasize = mail.emphasizer(RunnableLambda(lambda messages: AIMessage(next(answers))), {})
    assert await emphasize(text) == good and await emphasize(text) == good  # cached: the model is asked once
    other = text + " Today."
    assert await emphasize(other) == other  # a rewording is rejected and the original kept


async def test_an_approved_correction_enters_the_ledger_and_can_be_marked_applied(folder, tmp_path):
    from faro.tools import make_tools

    hub = Hub(folder, tmp_path / "state")
    tools = {t.name: t for t in make_tools(hub)}
    assert "ledger is empty" in await tools["list_corrections"].ainvoke({})
    await tools["open_issue"].ainvoke({"title": "Art books short", "severity": "blocker", "summary": "s", "evidence": []})
    await tools["update_record"].ainvoke({"issue_id": "I-1", "headline": "Correct the receipt", "reason": "r", "needs_human": True, "human_reason": "x", "system": "SAP",
                                          "record": "goods receipt 5000413065", "changes": [{"field": "quantity", "old_value": "80000", "new_value": "8000"}]})
    assert hub.store.corrections() == []  # proposing changes nothing
    await hub.decide("A-1", approved=True)
    (row,) = hub.store.corrections("I-1")
    assert (row["system"], row["field"], row["old_value"], row["new_value"], row["applied_at"]) == ("SAP", "quantity", "80000", "8000", None)
    assert "corrections ledger" in hub.inbox[-1] and "80000 -> 8000" in await tools["list_corrections"].ainvoke({})
    assert "not yet changed in the system" in await tools["list_corrections"].ainvoke({})

    hub.mark_applied(row["id"], "Keyed in by Nils.")
    assert hub.store.corrections()[0]["applied_at"] and hub.issues["I-1"].history[-1]["kind"] == "applied" and "Keyed in by Nils." in hub.issues["I-1"].history[-1]["text"]
    assert "[log]" in hub.inbox[-1]
    issue_event = [e for e in hub.events if e["kind"] == "issue"][-1]
    assert issue_event["issue"]["corrections"][0]["applied_note"] == "Keyed in by Nils."  # the UI gets the ledger with the issue

    again = Hub(folder, tmp_path / "state")
    assert again.store.corrections()[0]["new_value"] == "8000" and [h["kind"] for h in again.issues["I-1"].history] == ["found", "proposed", "approved", "applied"]


async def test_the_team_can_log_what_happened_outside_faro(folder, tmp_path):
    hub = Hub(folder, tmp_path / "state")
    hub.open_issue("Art books short", "blocker", "s", [])
    hub.log_manual("I-1", " Called Paul Winter, he sends the call-off tonight. ")
    entry = hub.issues["I-1"].history[-1]
    assert entry["kind"] == "logged" and entry["text"] == "Called Paul Winter, he sends the call-off tonight."
    assert hub.inbox[-1].startswith("[log]") and "outside this system" in hub.inbox[-1]
    assert Hub(folder, tmp_path / "state").issues["I-1"].history[-1]["kind"] == "logged"


async def test_a_restart_announces_only_what_changed_in_folder_and_mailbox(folder, tmp_path):
    from faro import mail

    hub = Hub(folder, tmp_path / "state")
    watcher = asyncio.create_task(watch_folder(hub, 0.02))
    await until(lambda: any("Start your review" in m for m in hub.inbox))
    watcher.cancel()
    hub.open_issue("Something", "risk", "s", [])
    (folder / "arrived_while_down.txt").write_text("late")

    again = Hub(folder, tmp_path / "state")  # the next process
    watcher = asyncio.create_task(watch_folder(again, 0.02))
    try:
        await until(lambda: len(again.inbox) >= 3)
        assert again.inbox[0].startswith("[state]") and "I-1" in again.inbox[0] and "Start your review" not in "".join(again.inbox)
        assert again.inbox[1].startswith("[settings]")  # the team's standing instructions, told again after every restart
        assert "1 new" in again.inbox[2] and "arrived_while_down.txt" in again.inbox[2]
    finally:
        watcher.cancel()

    old = {"message_id": "<old>", "thread_id": "t1", "labels": ["received"], "from": "A <a@x.example>", "to": ["team@agentmail.to"], "subject": "old", "timestamp": "2026-11-21T10:00:00Z", "text": "old"}
    new = {"message_id": "<new>", "thread_id": "t1", "labels": ["received"], "from": "A <a@x.example>", "to": ["team@agentmail.to"], "subject": "new", "timestamp": "2026-11-21T11:00:00Z", "text": "came in while Faro was down"}
    box = mail.Mailbox("team@agentmail.to", "test-key", fake_mail_service([], [old]))
    first = asyncio.create_task(mail.watch_mail(again, box, 0.02))
    await until(lambda: again.store.seen_mail() == {"<old>"})
    first.cancel()
    third = Hub(folder, tmp_path / "state")  # and the process after that
    box = mail.Mailbox("team@agentmail.to", "test-key", fake_mail_service([], [new, old]))
    second = asyncio.create_task(mail.watch_mail(third, box, 0.02))
    try:
        await until(lambda: any("came in while Faro was down" in m for m in third.inbox))
        assert not any("A new message arrived" in m and "\n\nold" in m for m in third.inbox)  # the old one is not news again
    finally:
        second.cancel()


def test_the_json_files_from_before_the_database_are_imported_once(folder, tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    issue = {"id": "I-1", "title": "Old issue", "severity": "risk", "summary": "s", "evidence": [], "next_step": "", "status": "open", "thread_ids": ["t1"], "replies": 1,
             "history": [{"ts": 1.0, "kind": "found", "text": "s", "ref": ""}], "created": 1.0, "updated": 1.0}
    approval = {"id": "A-1", "issue_id": "I-1", "tool": "send_email", "args": {}, "headline": "h", "reason": "r"}
    (state / "state.json").write_text(json.dumps({"auto": True, "events": [{"seq": 1, "ts": 1.0, "kind": "agent", "text": "hello"}], "issues": [issue], "approvals": [approval]}))
    (state / "translations.json").write_text(json.dumps({"<m>": {"v": 2, "language": "Polish", "summary": "s", "english": "e"}}))
    hub = Hub(folder, state)
    assert hub.restored and hub.auto and hub.issues["I-1"].replies == 1 and hub.approvals["A-1"].needs_human and hub.events[0]["text"] == "hello"
    assert hub.store.cache("translations")["<m>"]["english"] == "e"
    assert not (state / "state.json").exists() and (state / "state-imported-into-faro-db.json").exists()


def test_a_record_change_approved_before_the_ledger_is_entered_at_start(folder, tmp_path):
    hub = Hub(folder, tmp_path / "state")
    hub.open_issue("Old", "risk", "s", [])
    old = hub.propose("update_record", {"system": "SAP", "record": "GR 1", "changes": {"quantity": "8000"}}, "I-1", "h", "r")
    old.status = "approved"
    hub.store.put_approval(__import__("dataclasses").asdict(old))
    again = Hub(folder, tmp_path / "state")
    (row,) = again.store.corrections()
    assert (row["approval_id"], row["field"], row["old_value"], row["new_value"]) == ("A-1", "quantity", "", "8000")
    assert len(Hub(folder, tmp_path / "state").store.corrections()) == 1  # and only once


@pytest.mark.skipif(not __import__("os").environ.get("FARO_TEST_POSTGRES"), reason="set FARO_TEST_POSTGRES to a throwaway Postgres URL")
async def test_the_record_works_the_same_on_postgres_and_takes_over_a_local_one(folder, tmp_path):
    import os

    import psycopg

    url = os.environ["FARO_TEST_POSTGRES"]
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute("DROP SCHEMA IF EXISTS faro CASCADE")

    local = Hub(folder, tmp_path / "state")  # a record that started life in the local file
    local.open_issue("Art books short", "blocker", "s", ["erp.csv"])
    local.propose("update_record", {"system": "SAP", "record": "GR 1", "changes": [{"field": "qty", "old_value": "80000", "new_value": "8000"}]}, "I-1", "Correct", "r")
    await local.decide("A-1", approved=True)
    local.store.cache("translations")["<m>"] = {"v": 2, "english": "żółć stays intact"}
    local.store.remember_files({"a.csv": (10, 99)})

    hosted = Hub(folder, tmp_path / "state", url)  # first start on the hosted database: it takes the local record over
    assert hosted.restored and hosted.issues["I-1"].title == "Art books short" and hosted.approvals["A-1"].outcome == "recorded"
    assert [h["kind"] for h in hosted.issues["I-1"].history] == ["found", "proposed", "approved"]
    assert hosted.store.corrections()[0]["new_value"] == "8000" and hosted.store.known_files() == {"a.csv": (10, 99)}
    assert hosted.store.cache("translations")["<m>"]["english"] == "żółć stays intact"

    hosted.log_manual("I-1", "Called Paul.")
    hosted.mark_applied(hosted.store.corrections()[0]["id"], "Keyed in.")
    hosted.store.remember_mail(["<a>", "<b>"])
    hosted.store.remember_mail(["<b>", "<c>"])
    hosted.set_auto(True)
    hosted.store.close()

    again = Hub(folder, tmp_path / "state", url)  # a restart on the hosted database: nothing is imported twice
    assert len(again.events) == len(hosted.events) and again.auto
    assert [h["kind"] for h in again.issues["I-1"].history] == ["found", "proposed", "approved", "logged", "applied"]
    assert again.store.corrections()[0]["applied_note"] == "Keyed in." and again.store.seen_mail() == {"<a>", "<b>", "<c>"}
    assert again.open_issue("Second", "risk", "s", []).id == "I-2"
    again.store.close()


async def test_the_team_sets_objectives_mode_and_suppliers_and_the_agent_is_told(folder, tmp_path):
    from faro.tools import make_tools

    hub = Hub(folder, tmp_path / "state")
    tools = {t.name: t for t in make_tools(hub)}
    assert "no objectives" in hub.directives() and "supplier list is empty" in hub.directives() and "Aggressive mode is off" in hub.directives()

    hub.update_settings(objectives=["Ship every Collector's Edition on Sunday", "  ", "Spend as little as possible on express freight"])
    assert hub.objectives == ["Ship every Collector's Edition on Sunday", "Spend as little as possible on express freight"]
    told = hub.inbox[-1]
    assert told.startswith("[settings]") and told.index("1. Ship every") < told.index("2. Spend as little") and "the higher one wins" in told

    hub.update_settings(objectives=list(reversed(hub.objectives)))  # the team re-ranks them
    assert "1. Spend as little" in hub.inbox[-1]

    hub.update_settings(aggressive=True)
    hard = hub.inbox[-1]
    assert "Aggressive mode is ON" in hard and "never invent a competing" in hard and "needs_human" in hard
    assert "left out of future projects" in hard and "can be cancelled" in hard  # it may threaten the relationship
    assert "does not make up what has happened" in hard and "Do not insult" in hard  # but not lie or abuse

    await tools["save_supplier"].ainvoke({"name": "Karton Nowak", "contact": "Agnieszka Nowak", "email": "a.nowak@supplier.example", "language": "Polish"})
    assert "Error" in await tools["save_supplier"].ainvoke({"name": "Pune Diecast", "email": "ask reception"})
    before = len(hub.inbox)
    assert hub.suppliers[0]["by_team"] is False and len(hub.inbox) == before  # the agent's own additions are not announced back to it

    hub.update_settings(suppliers=[{"name": "Karton Nowak", "contact": "Agnieszka Nowak", "email": "orders@supplier.example", "language": "Polish", "notes": "Orders only via Paul Winter", "by_team": True}])
    assert "orders@supplier.example" in hub.inbox[-1] and "the list is right" in hub.inbox[-1]
    assert "their version stands" in await tools["save_supplier"].ainvoke({"name": "karton nowak", "email": "a.nowak@supplier.example"})
    assert hub.suppliers[0]["email"] == "orders@supplier.example" and "edited by the team" in await tools["list_suppliers"].ainvoke({})

    again = Hub(folder, tmp_path / "state")  # all of it survives a restart
    assert again.aggressive and again.objectives[0].startswith("Spend") and again.suppliers[0]["notes"] == "Orders only via Paul Winter"


async def test_hard_tone_reaches_the_email_writer_only_in_aggressive_mode(folder, tmp_path):
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda

    from faro import mail

    prompts = []

    def fake_sonnet(messages):
        prompts.append(messages[0][1])
        return AIMessage("SUBJECT: s\nBODY:\nb\nENGLISH:\nSAME")

    hub = Hub(folder, tmp_path / "state")
    write = mail.writer(RunnableLambda(fake_sonnet), "ctx", hard=lambda: hub.aggressive)
    await write("A", "English", "brief")
    hub.update_settings(aggressive=True)
    await write("A", "English", "brief")
    assert "aggressive negotiation" not in prompts[0] and "aggressive negotiation" in prompts[1] and "exclusion from future projects" in prompts[1] and "add nothing the brief does not contain" in prompts[1]


async def test_the_agent_withdraws_a_proposal_instead_of_asking_for_a_rejection(folder, tmp_path):
    from faro.tools import make_tools

    sent = []

    async def send(approval):
        sent.append(approval.id)
        return "Sent."

    hub = Hub(folder, tmp_path / "state")
    hub.executors["send_email"] = send
    withdraw = next(t for t in make_tools(hub) if t.name == "withdraw_proposal")
    issue = hub.open_issue("Art books short", "blocker", "s", [])
    hub.propose("send_email", {"to": ["a@x.example"]}, issue.id, "Send the call-off", "r", needs_human=False)
    assert "withdrawn" in await withdraw.ainvoke({"approval_id": "A-1", "reason": "A teammate already sent it at 17:37."})
    assert hub.approvals["A-1"].status == "withdrawn" and issue.history[-1]["kind"] == "withdrawn" and "already sent it" in issue.history[-1]["text"]
    hub.set_auto(True)  # a withdrawn proposal is never carried out, not even by auto mode
    await asyncio.sleep(0.05)
    assert sent == []
    with pytest.raises(ValueError):
        await hub.decide("A-1", approved=True)
    assert "Only a proposal that is still waiting" in await withdraw.ainvoke({"approval_id": "A-1", "reason": "again"})
    assert Hub(folder, tmp_path / "state").approvals["A-1"].status == "withdrawn"


async def test_an_enabled_adapter_posts_corrections_and_tracks_them(folder, tmp_path):
    hub = Hub(folder, tmp_path / "state")
    issue = hub.open_issue("Art books short", "blocker", "s", [])
    record = {"system": "SAP", "record": "goods receipt 5000413065", "changes": [{"field": "quantity", "old_value": "80000", "new_value": "8000"}]}

    before = hub.propose("update_record", record, issue.id, "Correct the receipt", "r")
    await hub.decide("A-1", approved=True)
    (waiting,) = hub.store.corrections()
    assert not before.live and waiting["applied_at"] is None  # no adapter: the ledger only
    with pytest.raises(ValueError, match="No adapter is enabled"):
        await hub.reconcile(waiting["id"])

    assert [a["id"] for a in hub.settings()["adapters"]] == ["soony-sap"] and not hub.settings()["adapters"][0]["enabled"]
    hub.update_settings(adapters_on={"soony-sap": True, "made-up": True})
    assert hub.adapters_on == {"soony-sap": True} and "Reconciliation is on for: SAP" in hub.inbox[-1]

    posted = await hub.reconcile(waiting["id"])  # the reviewer reconciles the one that was waiting
    assert posted["applied_at"] and "Posted through the Soony SAP adapter, reference REC-" in posted["applied_note"]
    assert issue.history[-1]["kind"] == "reconciled"
    with pytest.raises(ValueError, match="already in the system"):
        await hub.reconcile(waiting["id"])

    after = hub.propose("update_record", record | {"record": "stock batch 5000413065"}, issue.id, "Correct the stock", "r")
    assert after.live  # with an adapter on, approving a correction posts it
    await hub.decide("A-2", approved=True)
    rows = hub.store.corrections()
    assert rows[1]["applied_at"] and [h["kind"] for h in issue.history][-2:] == ["approved", "auto_reconciled"]
    assert "posted to SAP through its adapter" in hub.inbox[-1]

    again = Hub(folder, tmp_path / "state")
    assert again.settings()["adapters"][0]["enabled"] and all(c["applied_at"] for c in again.store.corrections())


async def test_an_outside_step_names_its_owner_and_the_team_can_mark_it_done(folder, tmp_path):
    from faro.tools import make_tools

    hub = Hub(folder, tmp_path / "state")
    tools = {t.name: t for t in make_tools(hub)}
    await tools["open_issue"].ainvoke({"title": "Art books short", "severity": "blocker", "summary": "s", "evidence": [],
                                       "next_step": "Paul Winter to send the order confirmation to Karton Nowak.", "next_owner": "Paul Winter"})
    issue = hub.issues["I-1"]
    assert issue.next_owner == "Paul Winter"
    await tools["update_issue"].ainvoke({"issue_id": "I-1", "note": "Truck still unconfirmed.", "next_step": "Raj Patel to book our own carrier.", "next_owner": "Raj Patel"})
    assert issue.next_owner == "Raj Patel"

    hub.step_done("I-1")
    assert issue.next_step == "" and issue.next_owner == "" and issue.history[-1] == issue.history[-1] | {"kind": "step_done", "text": "Raj Patel to book our own carrier."}
    assert hub.inbox[-1].startswith("[log]") and "as done by Raj Patel" in hub.inbox[-1]
    with pytest.raises(ValueError):
        hub.step_done("I-1")  # nothing is waiting any more

    await tools["update_issue"].ainvoke({"issue_id": "I-1", "note": "All arrived.", "next_step": "none", "next_owner": "Paul Winter"})
    assert issue.next_owner == ""  # no step, so nobody to wait on
    assert Hub(folder, tmp_path / "state").issues["I-1"].history[-2]["kind"] == "step_done"


def test_the_run_calculator_finds_what_stops_the_line_and_when():
    from faro import simulate

    cases = {"name": "cases", "per_unit": 1, "on_hand": 96000}
    plan = simulate.run(128000, 6000, 30, [cases | {"arrivals": [{"quantity": 350000, "at_hour": 10}]}])
    assert plan["made"] == 128000 and plan["short"] == 0 and plan["stops"] == [] and abs(plan["finished_at_hour"] - 21.35) < 0.1

    late = simulate.run(128000, 6000, 30, [cases | {"arrivals": [{"quantity": 350000, "at_hour": 27}]}])
    assert late["stops"][0]["part"] == "cases" and abs(late["stops"][0]["hour"] - 16) < 0.1 and late["stops"][0]["made_by_then"] == 96000
    assert 113000 < late["made"] < 115000 and late["short"] == 128000 - late["made"] and abs(late["idle_hours"] - 11) < 0.2  # 3 hours of packing after an 11-hour stop

    never = simulate.run(128000, 6000, 30, [cases])
    assert never["made"] == 96000 and never["short"] == 32000

    two = simulate.run(25200, 900, 30, [{"name": "art books", "per_unit": 1, "on_hand": 19300}, {"name": "magnets", "per_unit": 4, "on_hand": 200000}])
    assert two["made"] == 19300 and two["stops"][0]["part"] == "art books" and two["left_over"]["magnets"] == 200000 - 4 * 19300
    assert "ran out of art books" in simulate.describe(two) and "5,900 short" in simulate.describe(two)


async def test_the_outlook_holds_scenarios_with_or_without_an_issue(folder, tmp_path):
    from faro.tools import make_tools

    hub = Hub(folder, tmp_path / "state")
    tools = {t.name: t for t in make_tools(hub)}
    hub.open_issue("Art books short", "blocker", "s", [])
    scenario = {"what": "The carrier does not confirm a truck by 22:00.", "likelihood": "high", "why": "No confirmation in three hours.",
                "impact": "5,900 Collector's Editions cannot be packed.", "prevention": "Ask Karton Nowak now to confirm the truck's departure time.",
                "watch_for": "No email from Warta Trans by 22:00.", "response": "Ask Raj Patel to book Soony's own carrier from Poznań."}
    assert "Recorded as S-1" in await tools["anticipate"].ainvoke(scenario | {"issue_id": "I-1"})
    assert "Recorded as S-2" in await tools["anticipate"].ainvoke(scenario | {"what": "Customs holds the Boise shipment in Frankfurt."})  # no issue covers this yet
    assert "no issue 'I-9'" in await tools["anticipate"].ainvoke(scenario | {"issue_id": "I-9"})
    issue = hub.issues["I-1"]
    assert [s["issue_id"] for s in hub.scenarios] == ["I-1", ""] and not hub.approvals  # a possibility asks nothing of anyone
    assert issue.history[-1]["kind"] == "anticipated" and issue.history[-1]["ref"] == "S-1"
    assert any(e["kind"] == "outlook" and len(e["value"]["scenarios"]) == 2 for e in hub.events)  # the page is told

    assert "ran out" in await tools["simulate_run"].ainvoke({"units_needed": 25200, "rate_per_hour": 900, "hours_available": 30, "parts": [{"name": "art books", "per_unit": 1, "on_hand": 19300}]})
    assert "set_forecast" not in tools  # the agent records scenarios and their measures, not a forecast

    hub.settle_scenario("S-2", happened=True, by_team=True)  # the reviewer clicks "this happened" on the one with no issue
    assert hub.scenarios[1]["status"] == "happened" and "opening an issue for it first" in hub.inbox[-1] and "book Soony's own carrier" in hub.inbox[-1]
    assert "settled as passed" in await tools["settle_scenario"].ainvoke({"scenario_id": "S-1", "happened": False, "note": "The truck was confirmed."})
    assert issue.history[-1]["kind"] == "scenario_passed"
    assert "already settled" in await tools["settle_scenario"].ainvoke({"scenario_id": "S-1", "happened": True})

    for n in range(8):
        await tools["anticipate"].ainvoke(scenario | {"what": f"Variant {n}."})
    assert "already holds eight open scenarios" in await tools["anticipate"].ainvoke(scenario | {"what": "A ninth."})

    assert not hub.forecasting and "Forecasting is off" in hub.directives()  # off until the team switches it on
    before = len(hub.inbox)
    hub.update_settings(forecasting=True)
    assert hub.settings()["forecasting"] and "Forecasting is on" in hub.inbox[before] and hub.inbox[-1].startswith("[lookahead]") and "not only your open issues" in hub.inbox[-1]
    again = Hub(folder, tmp_path / "state")
    assert again.forecasting  # the switch survives a restart
    assert [s["status"] for s in again.scenarios][:2] == ["passed", "happened"]


async def test_the_look_ahead_timer_only_fires_while_forecasting_is_on(folder, tmp_path):
    from faro.agent import look_ahead_regularly

    hub = Hub(folder, tmp_path / "state")
    timer = asyncio.create_task(look_ahead_regularly(hub, 0.02 / 60))
    try:
        await asyncio.sleep(0.12)
        assert not any(m.startswith("[lookahead]") for m in hub.inbox)
        hub.update_settings(forecasting=True)
        hub.drain()
        await until(lambda: sum(m.startswith("[lookahead]") for m in hub.inbox) >= 2)
        hub.update_settings(forecasting=False)
        hub.drain()
        await asyncio.sleep(0.12)
        assert not any(m.startswith("[lookahead]") for m in hub.inbox)
    finally:
        timer.cancel()


def test_a_path_recorded_with_the_folder_name_in_front_still_opens(folder):
    assert files.read(folder, f"{folder.name}/context/notes.md") == files.read(folder, "context/notes.md")
    assert files.preview(folder, f"{folder.name}/erp.csv")["kind"] == "tables"
    with pytest.raises(files.FileError):
        files.read(folder, f"{folder.name}/../secret.txt")
    with pytest.raises(files.FileError):
        files.read(folder, f"{folder.name}/nothing-here.txt")


async def test_a_scenario_is_prevented_with_a_measure_proposed_now(folder, tmp_path):
    from faro.tools import make_tools

    sent = []

    async def send(approval):
        sent.append(approval.args["to"])
        approval.thread_id = "t9"
        return "Sent."

    hub = Hub(folder, tmp_path / "state")
    hub.executors["send_email"] = send
    tools = {t.name: t for t in make_tools(hub)}
    hub.open_issue("Art books short", "blocker", "s", [])
    base = {"what": "The art books reach the line too late.", "likelihood": "high", "why": "No truck confirmed.", "impact": "900 copies an hour.",
            "prevention": "Remind Karton Nowak that the truck has to leave by 04:00.", "watch_for": "No departure time by 03:00.", "response": "Book our own carrier."}
    told = await tools["anticipate"].ainvoke(base | {"issue_id": "I-1"})
    assert "Now act to prevent it" in told and hub.scenarios[0]["prevention"].startswith("Remind Karton Nowak")
    await tools["anticipate"].ainvoke(base | {"what": "Customs holds the Boise shipment."})  # belongs to no issue

    reminder = {"headline": "Remind Karton Nowak of the 04:00 departure", "reason": "So the truck is not late.", "needs_human": False, "human_reason": "A reminder; commits nothing.",
                "to": ["a.nowak@supplier.example"], "to_name": "A. Nowak", "language": "Polish", "brief": "Reminder\n\nPlease confirm the departure time."}
    assert "Queued as A-1" in await tools["send_email"].ainvoke(reminder | {"scenario_id": "S-1"})
    first = hub.approvals["A-1"]
    assert (first.scenario_id, first.issue_id) == ("S-1", "I-1") and hub.issues["I-1"].history[-1]["text"].endswith("(to prevent S-1)")  # the issue is taken from the scenario
    assert "Queued as A-2" in await tools["send_email"].ainvoke(reminder | {"scenario_id": "S-2"})
    assert (hub.approvals["A-2"].scenario_id, hub.approvals["A-2"].issue_id) == ("S-2", "")  # a measure can stand without an issue
    assert "no scenario 'S-9'" in await tools["send_email"].ainvoke(reminder | {"scenario_id": "S-9"})
    assert "say which issue this is for" in await tools["send_email"].ainvoke(reminder)
    assert sent == []  # nothing goes out on the agent's say-so

    await hub.decide("A-2", approved=True)  # approving a measure that has no issue works, and sends
    assert sent == [["a.nowak@supplier.example"]] and hub.approvals["A-2"].outcome == "done" and "against scenario S-2" in hub.inbox[-1]
    hub.set_auto(True)  # with auto mode on, the routine reminder goes out by itself
    await until(lambda: hub.approvals["A-1"].status == "approved")
    assert hub.approvals["A-1"].auto and hub.issues["I-1"].thread_ids == ["t9"]

    hub.settle_scenario("S-2", happened=False)
    assert "already settled" in await tools["send_email"].ainvoke(reminder | {"scenario_id": "S-2"})  # nothing left to prevent
    again = Hub(folder, tmp_path / "state")
    assert again.approvals["A-2"].scenario_id == "S-2" and again.scenarios[0]["prevention"].startswith("Remind")

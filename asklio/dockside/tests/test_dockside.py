import asyncio
import json

import pytest

from dockside import files
from dockside.agent import AgentRunner, watch_folder
from dockside.hub import Hub
from dockside.scripted import ScriptedModel


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

        hub.decide("A-1", approved=True, note="ok")
        await until(lambda: any(e["kind"] == "agent" and "decision noted" in e["text"] for e in hub.events))
        logged = json.loads((tmp_path / "state" / "actions.jsonl").read_text())
        assert logged["id"] == "A-1" and logged["status"] == "approved"

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
    hub.decide("A-1", approved=False, note="wrong batch")
    assert "REJECTED" in hub.inbox[-1] and "wrong batch" in hub.inbox[-1]
    assert not (tmp_path / "state" / "actions.jsonl").exists()
    with pytest.raises(ValueError):
        hub.decide("A-1", approved=True)


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
    from dockside import config

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

"""Local web server: serves the UI and connects it to the running agent."""
import asyncio
import json
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

from . import config, files, mail
from .agent import AgentRunner, watch_folder
from .hub import Hub


class ChatIn(BaseModel):
    text: str


class DecisionIn(BaseModel):
    approved: bool
    note: str = ""


def create_app(model=None, data_dir=None, state_dir=None, poll_seconds=None, mailbox=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        hub = Hub(data_dir or config.DATA_DIR, state_dir or config.STATE_DIR)
        app.state.hub = hub
        tasks = [asyncio.create_task(watch_folder(hub, poll_seconds or config.POLL_SECONDS))]
        try:
            chosen = model or config.MODEL
            if config.MAIL_ENABLED and chosen != "scripted" and mailbox is not False:  # the scripted stand-in must never send real mail
                hub.mailbox = mailbox or mail.Mailbox(config.MAIL_INBOX, config.MAIL_API_KEY)
                hub.executors["send_email"] = mail.sender(hub, hub.mailbox)
                try:
                    from langchain.chat_models import init_chat_model

                    mail_model = init_chat_model(config.MAIL_MODEL, max_tokens=8000)
                    hub.write_email = mail.writer(mail_model, config.BRIEF)
                    hub.translate_mail = mail.translator(mail_model, hub.state_dir / "translations.json")
                except Exception as err:
                    hub.emit("error", text=f"The mail model {config.MAIL_MODEL} could not be loaded ({err}). Emails will carry the agent's brief as their text.")
                tasks.append(asyncio.create_task(mail.watch_mail(hub, hub.mailbox, config.MAIL_POLL_SECONDS)))
            if isinstance(chosen, str) and chosen.startswith("anthropic:") and not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
                raise RuntimeError("no ANTHROPIC_API_KEY found")
            if chosen == "scripted":
                from .scripted import ScriptedModel

                chosen = ScriptedModel()
            tasks.append(asyncio.create_task(AgentRunner(hub, chosen).run_forever()))
        except Exception as err:  # most often: no API key for the chosen provider
            hub.emit("error", text=f"The agent could not start ({type(err).__name__}: {err}). Add the key to .env.local in the repo root, e.g. ANTHROPIC_API_KEY=..., and restart.")
        yield
        for task in tasks:
            task.cancel()

    app = FastAPI(lifespan=lifespan)

    @app.get("/")
    async def index():
        return FileResponse(config.WEB_DIR / "index.html")

    @app.get("/api/events")
    async def events(after: int = 0):
        hub: Hub = app.state.hub

        async def stream():
            queue = hub.subscribe()
            try:
                for event in hub.events[after:]:
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15)
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
            finally:
                hub.unsubscribe(queue)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.post("/api/chat")
    async def chat(body: ChatIn):
        if not body.text.strip():
            raise HTTPException(400, "Empty message.")
        app.state.hub.chat(body.text.strip())
        return {"ok": True}

    @app.post("/api/approvals/{approval_id}")
    async def decide(approval_id: str, body: DecisionIn):
        hub: Hub = app.state.hub
        if approval_id not in hub.approvals:
            raise HTTPException(404, f"No approval {approval_id}.")
        try:
            await hub.decide(approval_id, body.approved, body.note)
        except ValueError as err:
            raise HTTPException(409, str(err)) from None
        return {"ok": True}

    @app.get("/api/issues/{issue_id}/history")
    async def history(issue_id: str):
        """Everything that happened on an issue, in order: what the agent and the reviewer did, and the mail, read from the mailbox now."""
        hub: Hub = app.state.hub
        if issue_id not in hub.issues:
            raise HTTPException(404, f"No issue {issue_id}.")
        issue = hub.issues[issue_id]
        entries = [dict(entry) for entry in issue.history]
        problem = ""
        if hub.mailbox is not None:
            for thread_id in issue.thread_ids:
                try:
                    view = await mail.thread_view(hub, hub.mailbox, thread_id)
                except Exception as err:
                    problem = f"The mailbox could not be read: {err or type(err).__name__}"
                    continue
                for m in view["messages"]:
                    entries.append({"ts": mail.epoch(m["ts"]), "kind": "mail_" + m["direction"], "text": m["text"], "subject": view["subject"], **m})
        return {"entries": sorted(entries, key=lambda e: e["ts"]), "problem": problem}

    @app.get("/api/mail/threads")
    async def mail_threads():
        """Every conversation, read from the mailbox at the moment it is asked for."""
        hub: Hub = app.state.hub
        if hub.mailbox is None:
            return {"inbox": "", "threads": []}
        try:
            return {"inbox": hub.mailbox.inbox, "threads": [mail.thread_summary(hub.mailbox, t) for t in await hub.mailbox.threads()]}
        except Exception as err:
            raise HTTPException(502, f"The mailbox could not be read: {err or type(err).__name__}") from None

    @app.get("/api/threads/{thread_id:path}")
    async def thread(thread_id: str):
        hub: Hub = app.state.hub
        if hub.mailbox is None:
            raise HTTPException(404, "No mailbox is connected.")
        try:
            return await mail.thread_view(hub, hub.mailbox, thread_id)
        except Exception as err:
            raise HTTPException(502, f"The mailbox could not be read: {err or type(err).__name__}") from None

    @app.get("/api/preview")
    async def preview(path: str):
        try:
            return await asyncio.to_thread(files.preview, app.state.hub.data_dir, path)
        except files.FileError as err:
            raise HTTPException(400, str(err)) from None

    @app.get("/api/page")
    async def page(path: str, n: int = 0):
        try:
            data = await asyncio.to_thread(files.page_image, app.state.hub.data_dir, path, n)
        except files.FileError as err:
            raise HTTPException(400, str(err)) from None
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})

    @app.get("/api/file")
    async def file(path: str):
        hub: Hub = app.state.hub
        try:
            target = files.resolve(hub.data_dir, path)
        except files.FileError as err:
            raise HTTPException(400, str(err)) from None
        if not target.is_file():
            raise HTTPException(404, f"No file at {path}.")
        return FileResponse(target, content_disposition_type="inline")

    return app


def main() -> None:
    mailbox = config.MAIL_INBOX if config.MAIL_ENABLED and config.MODEL != "scripted" else "off"
    print(f"Faro: http://127.0.0.1:{config.PORT}  (model {config.MODEL}, watching {config.DATA_DIR}, mail {mailbox}, emails written by {config.MAIL_MODEL})")
    # Open event streams never close on their own; without a limit a stopped server lingers with the agent still running.
    uvicorn.run(create_app(), host="127.0.0.1", port=config.PORT, log_level="warning", timeout_graceful_shutdown=2)


if __name__ == "__main__":
    main()

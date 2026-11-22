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
from .agent import AgentRunner, look_ahead_regularly, watch_folder
from .hub import Hub


class ChatIn(BaseModel):
    text: str


class NoteIn(BaseModel):
    text: str = ""


class ScenarioIn(BaseModel):
    happened: bool


class RichIn(BaseModel):
    texts: list[str]


class AutoIn(BaseModel):
    on: bool


class SupplierIn(BaseModel):
    name: str
    contact: str = ""
    email: str = ""
    language: str = ""
    notes: str = ""
    by_team: bool = True


class SettingsIn(BaseModel):
    auto: bool | None = None
    aggressive: bool | None = None
    objectives: list[str] | None = None
    suppliers: list[SupplierIn] | None = None
    adapters: dict[str, bool] | None = None
    forecasting: bool | None = None


class DecisionIn(BaseModel):
    approved: bool
    note: str = ""


BRAND_FILES = {"faro-icon.png", "faro-logo.png", "Getboreg-Regular.ttf"}  # the only files served from brand/


def create_app(model=None, data_dir=None, state_dir=None, poll_seconds=None, mailbox=None, database_url=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        hub = Hub(data_dir or config.DATA_DIR, state_dir or config.STATE_DIR, config.DATABASE_URL if database_url is None else database_url)
        app.state.hub = hub
        tasks = []
        try:
            chosen = model or config.MODEL
            if chosen == "off":
                # No agent and no watchers: the record can be read and decided on, and nothing new is announced to
                # an agent that is not there. Mail and files that arrive meanwhile are picked up at the next real start.
                hub.emit("status", value="paused")
                if config.MAIL_ENABLED and mailbox is not False:
                    # A person approving an email is a decision that needs no agent: it is still sent. Nothing watches for the reply until the agent is back.
                    hub.mailbox = mailbox or mail.Mailbox(config.MAIL_INBOX, config.MAIL_API_KEY)
                    hub.executors["send_email"] = mail.sender(hub, hub.mailbox)
                yield
                hub.store.close()
                return
            tasks.append(asyncio.create_task(watch_folder(hub, poll_seconds or config.POLL_SECONDS)))
            chosen_name = chosen if isinstance(chosen, str) else ""
            if config.MAIL_ENABLED and chosen != "scripted" and mailbox is not False:  # the scripted stand-in must never send real mail
                hub.mailbox = mailbox or mail.Mailbox(config.MAIL_INBOX, config.MAIL_API_KEY)
                hub.executors["send_email"] = mail.sender(hub, hub.mailbox)
                try:
                    from langchain.chat_models import init_chat_model

                    mail_model = init_chat_model(config.MAIL_MODEL, max_tokens=8000)
                    hub.write_email = mail.writer(mail_model, config.BRIEF, hard=lambda: hub.aggressive)
                    hub.translate_mail = mail.translator(mail_model, hub.store.cache("translations"))
                    hub.summarize = mail.summarizer(mail_model, hub.store.cache("summaries"))
                    hub.emphasize = mail.emphasizer(mail_model, hub.store.cache("emphasis"))
                except Exception as err:
                    hub.emit("error", text=f"The mail model {config.MAIL_MODEL} could not be loaded ({err}). Emails will carry the agent's brief as their text.")
                tasks.append(asyncio.create_task(mail.watch_mail(hub, hub.mailbox, config.MAIL_POLL_SECONDS)))
            if isinstance(chosen, str) and chosen.startswith("anthropic:") and not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
                raise RuntimeError("no ANTHROPIC_API_KEY found")
            if chosen == "scripted":
                from .scripted import ScriptedModel

                chosen = ScriptedModel()
            tasks.append(asyncio.create_task(AgentRunner(hub, chosen).run_forever()))
            if chosen_name != "scripted":
                tasks.append(asyncio.create_task(look_ahead_regularly(hub, config.LOOKAHEAD_MINUTES)))
        except Exception as err:  # most often: no API key for the chosen provider
            hub.emit("error", text=f"The agent could not start ({type(err).__name__}: {err}). Add the key to .env.local in the repo root, e.g. ANTHROPIC_API_KEY=..., and restart.")
        yield
        for task in tasks:
            task.cancel()
        hub.store.close()  # lets queued writes to a hosted database finish

    app = FastAPI(lifespan=lifespan)

    @app.get("/")
    async def index():
        return FileResponse(config.WEB_DIR / "index.html")

    @app.get("/brand/{name}")
    async def brand(name: str):
        if name not in BRAND_FILES:
            raise HTTPException(404, "No such brand file.")
        return FileResponse(config.BRAND_DIR / name, headers={"Cache-Control": "public, max-age=86400"})

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

    @app.get("/api/outlook")
    async def get_outlook():
        return app.state.hub.outlook()

    @app.get("/api/scenarios/{scenario_id}/history")
    async def scenario_history(scenario_id: str):
        hub: Hub = app.state.hub
        scenario = next((s for s in hub.scenarios if s["id"] == scenario_id), None)
        if scenario is None:
            raise HTTPException(404, f"No scenario {scenario_id}.")
        return await mail.scenario_history(hub, scenario)

    @app.post("/api/scenarios/{scenario_id}")
    async def settle(scenario_id: str, body: ScenarioIn):
        try:
            return app.state.hub.settle_scenario(scenario_id, body.happened, by_team=True)
        except KeyError:
            raise HTTPException(404, f"No scenario {scenario_id}.") from None
        except ValueError as err:
            raise HTTPException(409, str(err)) from None

    @app.post("/api/issues/{issue_id}/done")
    async def done(issue_id: str):
        hub: Hub = app.state.hub
        if issue_id not in hub.issues:
            raise HTTPException(404, f"No issue {issue_id}.")
        try:
            hub.step_done(issue_id)
        except ValueError as err:
            raise HTTPException(409, str(err)) from None
        return {"ok": True}

    @app.post("/api/issues/{issue_id}/log")
    async def log(issue_id: str, body: NoteIn):
        hub: Hub = app.state.hub
        if issue_id not in hub.issues:
            raise HTTPException(404, f"No issue {issue_id}.")
        if not body.text.strip():
            raise HTTPException(400, "Nothing to record.")
        hub.log_manual(issue_id, body.text)
        return {"ok": True}

    @app.post("/api/corrections/{correction_id}/reconcile")
    async def reconcile(correction_id: int):
        try:
            return await app.state.hub.reconcile(correction_id)
        except KeyError:
            raise HTTPException(404, f"No correction {correction_id}.") from None
        except ValueError as err:
            raise HTTPException(409, str(err)) from None

    @app.post("/api/corrections/{correction_id}/applied")
    async def applied(correction_id: int, body: NoteIn):
        try:
            return app.state.hub.mark_applied(correction_id, body.text)
        except KeyError:
            raise HTTPException(404, f"No correction {correction_id}.") from None

    @app.post("/api/rich")
    async def rich(body: RichIn):
        """The same texts with their key facts in bold. A text that cannot be marked up comes back unchanged."""
        hub: Hub = app.state.hub

        async def one(text: str) -> str:
            if hub.emphasize is None:
                return text
            try:
                return await hub.emphasize(text)
            except Exception:
                return text

        return {"texts": list(await asyncio.gather(*(one(text) for text in body.texts[:40])))}

    @app.get("/api/settings")
    async def get_settings():
        return app.state.hub.settings()

    @app.post("/api/settings")
    async def set_settings(body: SettingsIn):
        suppliers = None if body.suppliers is None else [s.model_dump() for s in body.suppliers if s.name.strip()]
        return app.state.hub.update_settings(body.auto, body.aggressive, body.objectives, suppliers, adapters_on=body.adapters, forecasting=body.forecasting)

    @app.post("/api/auto")
    async def auto(body: AutoIn):
        app.state.hub.set_auto(body.on)
        return {"ok": True, "on": app.state.hub.auto}

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
        return await mail.issue_history(hub, hub.issues[issue_id])

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
    print(f"Faro: http://127.0.0.1:{config.PORT}  (model {config.MODEL}, watching {config.DATA_DIR}, mail {mailbox}, emails written by {config.MAIL_MODEL}, record in {config.DATABASE_URL.split("@")[-1].split("?")[0] if config.DATABASE_URL else "local SQLite"})")
    # Open event streams never close on their own; without a limit a stopped server lingers with the agent still running.
    uvicorn.run(create_app(), host="127.0.0.1", port=config.PORT, log_level="warning", timeout_graceful_shutdown=2)


if __name__ == "__main__":
    main()

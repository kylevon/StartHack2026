"""Local web server: serves the UI and connects it to the running agent."""
import asyncio
import json
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from . import config, files
from .agent import AgentRunner, watch_folder
from .hub import Hub


class ChatIn(BaseModel):
    text: str


class DecisionIn(BaseModel):
    approved: bool
    note: str = ""


def create_app(model=None, data_dir=None, state_dir=None, poll_seconds=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        hub = Hub(data_dir or config.DATA_DIR, state_dir or config.STATE_DIR)
        app.state.hub = hub
        tasks = [asyncio.create_task(watch_folder(hub, poll_seconds or config.POLL_SECONDS))]
        try:
            chosen = model or config.MODEL
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
            hub.decide(approval_id, body.approved, body.note)
        except ValueError as err:
            raise HTTPException(409, str(err)) from None
        return {"ok": True}

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
    print(f"Dockside: http://127.0.0.1:{config.PORT}  (model {config.MODEL}, watching {config.DATA_DIR})")
    uvicorn.run(create_app(), host="127.0.0.1", port=config.PORT, log_level="warning")


if __name__ == "__main__":
    main()

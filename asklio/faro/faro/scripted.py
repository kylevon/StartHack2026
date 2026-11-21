"""A stand-in model that follows a fixed script, for tests and for trying the UI with no API key.

Run with FARO_MODEL=scripted. It reads one file and raises one sample approval;
it does not reason about anything.
"""
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult


def _call(name: str, args: dict, n: int) -> dict:
    return {"name": name, "args": args, "id": f"scripted-{n}", "type": "tool_call"}


class ScriptedModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _reply(self, messages) -> AIMessage:
        last, n = messages[-1], len(messages)
        if isinstance(last, ToolMessage):
            if last.name == "list_files":
                lines = [line.split("  (")[0] for line in str(last.content).splitlines()[1:] if "  (" in line]
                if not lines:
                    return AIMessage("Scripted mode: the folder is empty, nothing to read.")
                target = next((p for p in lines if p.endswith(".md")), lines[0])
                content = [
                    {"type": "thinking", "thinking": f"Scripted thought: {target} looks like the place to start. A real model would explain here, at whatever length it needs, why it picked this file over the others in the folder and what it expects to learn from it before deciding what to do next."},
                    {"type": "text", "text": "Reading the first document to see what this folder is about."},
                ]
                return AIMessage(content, tool_calls=[_call("read_file", {"path": target}, n)])
            if last.name == "read_file":
                path = next(m for m in reversed(messages) if isinstance(m, AIMessage) and m.tool_calls).tool_calls[0]["args"]["path"]
                return AIMessage("", tool_calls=[_call("open_issue", {
                    "title": "Scripted sample: one delivery quantity to confirm", "severity": "info",
                    "summary": "Scripted mode produces this sample issue so the screen can be tried without a model. It is not a finding.",
                    "evidence": [path],
                }, n)])
            if last.name == "open_issue":
                return AIMessage("", tool_calls=[_call("send_email", {
                    "issue_id": "I-1", "headline": "Ask the sample supplier to confirm the quantity", "reason": "A sample action for the sample issue.",
                    "needs_human": True, "human_reason": "Scripted sample.",
                    "to": ["sample@example.com"], "to_name": "Sample Supplier", "language": "English",
                    "brief": "Sample: please confirm quantity\n\nHello,\n\nplease confirm the quantity shipped.\n\nThe team",
                }, n)])
            return AIMessage("Scripted mode: I read one file, opened one sample issue and queued one sample approval.")
        text = last.content if isinstance(last, HumanMessage) and isinstance(last.content, str) else ""
        if "[chat]" in text:
            return AIMessage("Scripted mode, no model connected. I received: " + text.split("[chat]", 1)[1].strip()[:200])
        if "[approval]" in text:
            return AIMessage("Scripted mode: decision noted.")
        if text.startswith("[files] You are connected"):
            return AIMessage("", tool_calls=[_call("list_files", {}, n)])
        return AIMessage("Scripted mode: noted the change in the folder.")

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._reply(messages))])

"""The agent's tools.

Reading tools run straight away. Tools that change something outside the agent
(email, files, records in other systems) never run on the agent's say-so: calling one queues
an approval for a person and returns at once, so the agent keeps working. The
decision comes back later as an injected `[approval]` message.
"""
import asyncio
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from . import files
from .hub import Hub

READ_TOOLS = {"list_files", "read_file", "search_files"}

Severity = Literal["blocker", "risk", "info"]


class Proposal(BaseModel):
    headline: str = Field(description="The problem in ten words or fewer, with the number that matters. Shown as the approval's title.")
    reason: str = Field(description="For a reviewer with no context: what you found, what it costs if ignored, and why this action and this recipient.")
    evidence: list[str] = Field(description="Paths of the files you read that back this up.")
    severity: Severity = Field(description="blocker: something important cannot go ahead without it. risk: may cost money, time or quality. info: housekeeping.")


class SendEmail(Proposal):
    to: str = Field(description="Recipient: name, and email address or role.")
    subject: str
    body: str = Field(description="Full email text in the recipient's preferred language.")
    language: str = Field(description="Language the body is written in, e.g. 'Polish'.")
    translation: str = Field(default="", description="English translation of the body when it is not in English.")


class EditFile(Proposal):
    path: str = Field(description="File to change, relative to the document folder.")
    find: str = Field(description="Exact text to replace. Must occur in the file.")
    replace: str = Field(description="Text to put in its place.")


class UpdateRecord(Proposal):
    system: str = Field(description="System that holds the record: an ERP, a CRM, a database, a tracker.")
    record: str = Field(description="Which record: its type and key, e.g. 'purchase order 4500001234'.")
    changes: dict[str, str] = Field(description="Field name to new value. Put the old value in the reason.")


def make_tools(hub: Hub) -> list:
    root = hub.data_dir

    @tool
    async def list_files(folder: str = "", pattern: str = "*") -> str:
        """List files in the document folder, recursively. `folder` narrows to a subfolder, `pattern` is a glob such as '*.pdf'."""
        try:
            return await asyncio.to_thread(files.list_files, root, folder, pattern)
        except files.FileError as err:
            return f"Error: {err}"

    @tool
    async def read_file(path: str, offset: int = 0):
        """Read one file of any common type: text, CSV, Excel, PDF, photo or scan. Text comes back as text; scanned PDF pages and images come back as images for you to read. Long files come in parts: `offset` continues where the previous call said to (a character position, or for PDFs a page number)."""
        try:
            return await asyncio.to_thread(files.read, root, path, offset)
        except files.FileError as err:
            return f"Error: {err}"

    @tool
    async def search_files(query: str, folder: str = "") -> str:
        """Find a string (a reference number, a code, a name) in file names and in the text of every file, including PDFs and spreadsheets. Text inside photos and scanned pages is not searchable."""
        try:
            return await asyncio.to_thread(files.search_files, root, query, folder)
        except files.FileError as err:
            return f"Error: {err}"

    def queue(name: str, proposal: Proposal) -> str:
        args = proposal.model_dump(exclude={"headline", "reason", "evidence", "severity"})
        approval = hub.propose(name, args, proposal.headline, proposal.reason, proposal.evidence, proposal.severity)
        return f"Queued as {approval.id}. Not done yet: a person has to approve it. Carry on with other work; the decision arrives as an [approval] message."

    @tool(args_schema=SendEmail)
    async def send_email(**kwargs) -> str:
        """Propose an email to anyone, inside or outside the team. Needs human approval before it is sent."""
        return queue("send_email", SendEmail(**kwargs))

    @tool(args_schema=EditFile)
    async def edit_file(**kwargs) -> str:
        """Propose replacing text in a file in the document folder. Needs human approval before it is applied."""
        proposal = EditFile(**kwargs)
        try:
            target = files.resolve(root, proposal.path)
        except files.FileError as err:
            return f"Error: {err}"
        if not target.is_file() or proposal.find not in await asyncio.to_thread(files.searchable_text, target):
            return f"Error: the text in `find` does not occur in '{proposal.path}'. Read the file and copy the text exactly."
        return queue("edit_file", proposal)

    @tool(args_schema=UpdateRecord)
    async def update_record(**kwargs) -> str:
        """Propose a change to a record in a business system or database: a quantity, a status, a master-data field. Needs human approval before it is posted."""
        return queue("update_record", UpdateRecord(**kwargs))

    return [list_files, read_file, search_files, send_email, edit_file, update_record]

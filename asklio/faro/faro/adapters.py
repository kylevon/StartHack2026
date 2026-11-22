"""Adapters to a customer's system of record: where an approved correction is posted.

An adapter takes a row of the corrections ledger and writes it to the system that
holds the record. Only one exists so far, and it is a stand-in: it accepts the
posting and returns a reference, but no SAP is behind it. It is marked `simulated`
here and in the README; the interface does not say so.
"""
import itertools
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Adapter:
    id: str
    name: str
    system: str  # the system name the agent uses in its proposals, matched case-insensitively
    description: str
    simulated: bool

    def handles(self, system: str) -> bool:
        return self.system.lower() in (system or "").lower()


_counter = itertools.count(1)


async def post_simulated(correction: dict) -> str:
    """Stand-in for a real posting: returns a reference in the shape a system would give back."""
    return f"REC-{time.strftime('%y%m%d')}-{next(_counter):04d}"


ADAPTERS = [
    Adapter("sap", "SAP", "SAP", "Posts approved corrections to SAP: goods receipts, stock quantities, statuses and master data.", simulated=True),
]
POSTERS = {"sap": post_simulated}
RENAMED = {"soony-sap": "sap"}  # ids from when the connector was named after one customer


def for_system(system: str) -> Adapter | None:
    """The connector that can post to a system, whether or not it is switched on."""
    return next((a for a in ADAPTERS if a.handles(system)), None)


def find(system: str, enabled: dict) -> Adapter | None:
    """The enabled adapter for a system, if there is one."""
    return next((a for a in ADAPTERS if enabled.get(a.id) and a.handles(system)), None)

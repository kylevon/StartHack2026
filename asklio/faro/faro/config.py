"""Settings, read once from the environment (and the repo's .env files)."""
import os
from pathlib import Path

from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parents[1]  # asklio/faro
REPO_DIR = APP_DIR.parents[1]

load_dotenv(REPO_DIR / ".env")
load_dotenv(REPO_DIR / ".env.local", override=True)  # untracked: API keys go here

DATA_DIR = Path(os.environ.get("FARO_DATA_DIR", APP_DIR.parent / "data" / "soony-data")).resolve()
STATE_DIR = Path(os.environ.get("FARO_STATE_DIR", APP_DIR / ".faro")).resolve()
# Hosted Postgres (e.g. Supabase) for the system of record. Empty: a local SQLite file in STATE_DIR.
DATABASE_URL = os.environ.get("FARO_DATABASE_URL", "")
MODEL = os.environ.get("FARO_MODEL", "anthropic:claude-opus-5-5")
POLL_SECONDS = float(os.environ.get("FARO_POLL_SECONDS", "5"))
PORT = int(os.environ.get("FARO_PORT", "8000"))
WEB_DIR = APP_DIR / "web"

# Team mailbox (AgentMail). With both set, approved emails are really sent and incoming mail reaches the agent.
MAIL_INBOX = os.environ.get("AGENTMAIL_INBOX", "")
MAIL_API_KEY = os.environ.get("AGENTMAIL_API_KEY", "")
LOOKAHEAD_MINUTES = float(os.environ.get("FARO_LOOKAHEAD_MINUTES", "30"))  # how often the agent re-simulates and updates the outlook; 0 turns the timer off
MAIL_ENABLED = bool(MAIL_INBOX and MAIL_API_KEY) and os.environ.get("FARO_MAIL", "on") != "off"
MAIL_MODEL = os.environ.get("FARO_MAIL_MODEL", "anthropic:claude-sonnet-5-5")  # writes the emails; the main model only briefs it
MAIL_POLL_SECONDS = float(os.environ.get("FARO_MAIL_POLL_SECONDS", "20"))
COMPACT_TOKENS = int(os.environ.get("FARO_COMPACT_TOKENS", "150000"))  # non-Claude models: summarise history past this size

# Optional plain-text description of whose documents these are and what matters to them.
_brief_path = Path(os.environ.get("FARO_BRIEF", APP_DIR / "brief.md"))
BRIEF = _brief_path.read_text().strip() if _brief_path.is_file() else ""

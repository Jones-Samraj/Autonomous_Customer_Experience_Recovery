from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.analytics.frames import DataView
from app.agents.llm import LLMClient
from app.core.config import Settings, get_settings
from app.services.system import get_sim_now


@dataclass
class AgentResult:
    output: dict
    reasoning: str
    inputs: dict = field(default_factory=dict)
    status: str = "succeeded"


class Ctx:
    """Everything an agent needs for one run. Agents read the signal store through ``view`` only."""

    def __init__(self, db: Session, run_id: str, issue_id: int | None = None, settings: Settings | None = None):
        self.db = db
        self.s = settings or get_settings()
        self.run_id = run_id
        self.issue_id = issue_id
        self.now: datetime = get_sim_now(db)
        self.view = DataView(db, self.now, self.s)
        self.llm = LLMClient(self.s)
        self.flags: dict = {}

    def refresh_view(self) -> None:
        self.now = get_sim_now(self.db)
        self.view = DataView(self.db, self.now, self.s)

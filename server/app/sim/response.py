"""How the simulated enterprise reacts to executed actions.

Executing an operational change in a simulated system alters the hidden world (a mitigation on any causal factor of a
matching cause type). Investigation agents never see factor identifiers - they only observe the resulting data.
"""
from __future__ import annotations

import zlib
from datetime import datetime

import numpy as np
from sqlalchemy.orm import Session

from app.agents.domain import INTERVENTIONS
from app.services.system import get_setting, get_sim_now, set_setting
from app.sim.world import iso


def apply_change(db: Session, code: str, itype: str, aspect: str | None) -> dict:
    state = get_setting(db, "world_state")
    if not state:
        return {"applied": False, "reason": "no simulated world connected"}
    spec = INTERVENTIONS[itype]
    now = get_sim_now(db)
    rng = np.random.default_rng(zlib.crc32(code.encode()))
    touched = 0
    for f in state["factors"]:
        eff = spec["addresses"].get(f.get("cause_type"), 0.0)
        if eff > 0 and f.get("target"):
            f.setdefault("mitigations", []).append({"from": iso(now), "eff": float(min(0.97, eff * rng.uniform(0.85, 1.05))), "by": code})
            touched += 1
    if spec.get("complaint_mult"):
        state.setdefault("voice_mults", []).append({"from": iso(now), "aspect": aspect or "*", "mult": spec["complaint_mult"], "by": code})
        touched += 1
    set_setting(db, "world_state", state)
    return {"applied": True, "effective_from": iso(now), "systems_updated": touched}


def revert_change(db: Session, code: str) -> dict:
    state = get_setting(db, "world_state")
    if not state:
        return {"reverted": False}
    now = iso(get_sim_now(db))
    n = 0
    for f in state["factors"]:
        for m in f.get("mitigations", []):
            if m.get("by") == code and not m.get("until"):
                m["until"] = now
                n += 1
    for vm in state.get("voice_mults", []):
        if vm.get("by") == code and not vm.get("until"):
            vm["until"] = now
            n += 1
    set_setting(db, "world_state", state)
    return {"reverted": True, "effective_from": now, "systems_updated": n}


def now_iso(dt: datetime) -> str:
    return iso(dt)

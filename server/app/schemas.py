from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class UserCreate(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=190)
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=10, max_length=128)
    role: str = Field(pattern="^(viewer|analyst|approver|admin)$")


class SignalRecords(BaseModel):
    dataset_type: str
    records: list[dict] = Field(min_length=1, max_length=5000)
    source_name: str | None = Field(default=None, max_length=160)


class DecisionIn(BaseModel):
    comment: str | None = Field(default=None, max_length=1000)


class AdvanceIn(BaseModel):
    days: int = Field(default=7, ge=1, le=30)


class InjectionIn(BaseModel):
    type: str
    params: dict = Field(default_factory=dict)


class ScenarioIn(BaseModel):
    issue_id: int
    name: str | None = Field(default=None, max_length=160)
    preset: str | None = None
    injections: list[InjectionIn] = Field(default_factory=list)

    @field_validator("injections")
    @classmethod
    def _limit(cls, v):
        if len(v) > 10:
            raise ValueError("At most 10 injections per scenario")
        return v


class RetentionIn(BaseModel):
    days: int = Field(ge=7, le=3650)

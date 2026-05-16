"""Pydantic request/response schemas for the session HTTP surface."""

from __future__ import annotations

from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field


class FavoritesPatchRequest(BaseModel):
    add: list[str] = Field(default_factory=list)
    remove: list[str] = Field(default_factory=list)


class PrefsPatchRequest(BaseModel):
    merge: dict[str, Any] = Field(default_factory=dict)


class SessionPatchRequest(BaseModel):
    favorites: FavoritesPatchRequest | None = None
    prefs: PrefsPatchRequest | None = None
    cookies_consent: Literal["accepted", "declined"] | None = None

    model_config = ConfigDict(extra="forbid")


class SessionView(BaseModel):
    kind: str
    user_id: str | None
    capabilities: list[str]
    prefs: Mapping[str, Any]
    favorites: list[str]
    cookies_consent: Literal["accepted", "declined"] | None = None

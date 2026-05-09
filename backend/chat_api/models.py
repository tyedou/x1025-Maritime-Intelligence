"""Typed request/response models for the chat API."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class TableInfo(BaseModel):
    name: str = Field(..., description="Display name (file stem)")
    path: str = Field(..., description="Absolute path to the .lance directory")
    is_active: bool = Field(False, description="Whether this is the currently selected table")


class TableListResponse(BaseModel):
    tables: list[TableInfo]
    active: Optional[str] = Field(None, description="Path of the active table, if any")


class TableSelectRequest(BaseModel):
    path: str = Field(..., description="Path returned by GET /api/v1/tables")


class TableSelectResponse(BaseModel):
    active: str


class HealthResponse(BaseModel):
    status: Literal["ok", "loading", "error"]
    agent_loaded: bool
    active_table: Optional[str] = None
    mock: bool


# WebSocket message envelope. Sent by client and server.
class WsClientMessage(BaseModel):
    type: Literal["question"]
    question: str
    k: int = 100
    top_n: int = 15


class WsServerStart(BaseModel):
    type: Literal["start"] = "start"
    table: Optional[str] = None


class WsServerToken(BaseModel):
    type: Literal["token"] = "token"
    text: str


class WsServerSources(BaseModel):
    type: Literal["sources"] = "sources"
    chunks: list[dict]


class WsServerEnd(BaseModel):
    type: Literal["end"] = "end"


class WsServerError(BaseModel):
    type: Literal["error"] = "error"
    message: str

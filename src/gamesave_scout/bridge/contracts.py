"""JSON-safe response envelopes shared by all bridge methods."""

from __future__ import annotations

type JSONPrimitive = str | int | float | bool | None
type JSONValue = JSONPrimitive | list["JSONValue"] | dict[str, "JSONValue"]
type ApiResult = dict[str, JSONValue]


def success(data: JSONValue) -> ApiResult:
    return {"ok": True, "data": data}


def failure(code: str, message: str, *, details: JSONValue = None) -> ApiResult:
    error: dict[str, JSONValue] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"ok": False, "error": error}

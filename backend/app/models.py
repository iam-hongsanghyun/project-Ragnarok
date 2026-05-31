from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class RunPayload(BaseModel):
    model: dict[str, list[dict[str, Any]]]
    scenario: dict[str, Any]
    options: dict[str, Any] | None = None

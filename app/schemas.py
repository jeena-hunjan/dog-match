"""Pydantic models used at the API boundary."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"]
    model_loaded: bool

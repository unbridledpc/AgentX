from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter

from agentx_api.judgment_controller import classify_judgment, judgment_policy

router = APIRouter(prefix="/judgment", tags=["Judgment"])


class JudgmentRequest(BaseModel):
    text: str = Field(default="", description="User input or candidate prompt to classify before inference.")
    context_turns: int = Field(default=0, ge=0, description="Approximate number of prior turns in active context.")
    previous_error: bool = Field(default=False, description="Whether this classification follows a failed tool/model/validation run.")


@router.post("/classify")
def classify(req: JudgmentRequest) -> dict:
    return classify_judgment(req.text, context_turns=req.context_turns, previous_error=req.previous_error)


@router.get("/policy")
def policy() -> dict:
    return {"ok": True, "policy": judgment_policy()}

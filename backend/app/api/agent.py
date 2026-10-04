from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.agent.coordinator import Coordinator

router = APIRouter(
    prefix="/api/agent",
    tags=["agent"],
)


class AgentRequest(BaseModel):
    request: str
    origin: tuple[float, float]


@router.post("/mission")
def process_mission(data: AgentRequest, request: Request):
    coordinator = Coordinator(
        request.app.state.planner,
        request.app.state.simulation,
    )

    return coordinator.process(
        data.request,
        data.origin,
    )
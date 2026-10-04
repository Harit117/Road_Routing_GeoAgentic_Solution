from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/agent", tags=["agent"])


class MissionRequest(BaseModel):
    request: str = Field(
        description="Natural-language emergency mission request"
    )

    origin: tuple[float, float] = Field(
        description="Mission origin as (longitude, latitude)"
    )


class ReassessRequest(BaseModel):
    origin: tuple[float, float] = Field(
        description="Current vehicle position as (longitude, latitude)"
    )


@router.post("/mission")
def create_mission(
    body: MissionRequest,
    request: Request,
):
    """
    Create a mission, assess the current hazard,
    and calculate a flood-aware route.
    """

    coordinator = request.app.state.coordinator

    try:
        result = coordinator.process(
            body.request,
            body.origin,
        )

        # Store the active mission so that it can be reassessed later.
        request.app.state.active_mission = result["mission"]

        return result

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


@router.post("/reassess")
def reassess_mission(
    body: ReassessRequest,
    request: Request,
):
    """
    Reassess the active mission after the environment changes.

    The Coordinator compares the previous hazard state with
    the current state and reroutes if necessary.
    """

    coordinator = request.app.state.coordinator
    mission_data = request.app.state.active_mission

    if mission_data is None:
        raise HTTPException(
            status_code=409,
            detail="No active mission. Create a mission first.",
        )

    # Reconstruct the MissionState object from the stored data.
    from app.mission.state import MissionState

    mission_state = MissionState(**mission_data)

    try:
        result = coordinator.reassess(
            mission_state,
            body.origin,
        )

        request.app.state.active_mission = result["mission"]

        return result

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )
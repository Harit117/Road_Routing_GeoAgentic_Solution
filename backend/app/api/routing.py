from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.routing.missions import MISSIONS

router = APIRouter(prefix="/api", tags=["routing"])


class RouteRequest(BaseModel):
    mission: str
    origin: tuple[float, float]  # (lon, lat)
    destination: tuple[float, float] | None = None


@router.get("/missions")
def missions():
    return [asdict(m) for m in MISSIONS.values()]


@router.post("/route")
def route(body: RouteRequest):
    raise HTTPException(501, "flood-aware A* routing is not implemented yet")

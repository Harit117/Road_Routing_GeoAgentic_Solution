"""Registry of available flood models. Register new models here."""

from app.simulation.flood_models.base import FloodModel
from app.simulation.flood_models.placeholder_bucket import PlaceholderBucketModel
from app.simulation.flood_models.susceptibility_bucket import SusceptibilityBucketModel

MODELS: dict[str, type[FloodModel]] = {
    SusceptibilityBucketModel.name: SusceptibilityBucketModel,
    PlaceholderBucketModel.name: PlaceholderBucketModel,
}

# The map, the simulation endpoints and routing all use this unless a request
# picks another model.
DEFAULT_MODEL = SusceptibilityBucketModel.name


def create_model(name: str) -> FloodModel:
    return MODELS[name]()

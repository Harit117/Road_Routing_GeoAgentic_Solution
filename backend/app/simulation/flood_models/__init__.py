"""Registry of available flood models. Register new models here."""

from app.simulation.flood_models.base import FloodModel
from app.simulation.flood_models.placeholder_bucket import PlaceholderBucketModel

MODELS: dict[str, type[FloodModel]] = {
    PlaceholderBucketModel.name: PlaceholderBucketModel,
}

DEFAULT_MODEL = PlaceholderBucketModel.name


def create_model(name: str) -> FloodModel:
    return MODELS[name]()

import json
from pathlib import Path


# ---------------------------------------------------------
# Load facility data
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parents[2]

FACILITY_FILE = BASE_DIR / "data" / "sample_facilities.json"


with open(FACILITY_FILE, "r", encoding="utf-8") as f:
    FACILITY_DATA = json.load(f)


FACILITIES = FACILITY_DATA["facilities"]


# ---------------------------------------------------------
# Facility Resolver
# ---------------------------------------------------------

class FacilityResolver:

    def __init__(self):
        self.facilities = FACILITIES


    # -----------------------------------------------------
    # Find facilities by type
    # -----------------------------------------------------

    def find_by_type(self, facility_type: str):

        facility_type = facility_type.lower().strip()

        return [
            facility
            for facility in self.facilities
            if facility["type"].lower() == facility_type
        ]


    # -----------------------------------------------------
    # Find facility by ID
    # -----------------------------------------------------

    def find_by_id(self, facility_id: str):

        facility_id = facility_id.upper().strip()

        for facility in self.facilities:

            if facility["id"] == facility_id:
                return facility

        return None
import os
import json
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from .prompts import MISSION_SYSTEM_PROMPT
from .schemas import (
    MissionExtraction,
    MissionProfile,
    MISSION_DEFAULTS,
)


# ---------------------------------------------------------
# Load .env from project root
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parents[3]
load_dotenv(BASE_DIR / ".env")


# ---------------------------------------------------------
# Mission Agent
# ---------------------------------------------------------

class MissionAgent:

    def __init__(self):

        self.model = ChatOpenAI(
            model=os.getenv("OPENROUTER_MODEL"),
            temperature=0,
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url="https://openrouter.ai/api/v1",
        )

        self.structured_model = self.model


    # -----------------------------------------------------
    # Analyze mission request
    # -----------------------------------------------------

    def analyze(self, user_request: str) -> MissionProfile:

        messages = [
            {
                "role": "system",
                "content": MISSION_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": user_request,
            },
        ]

        # First attempt
        response = self.structured_model.invoke(messages)

        print("\nRAW MODEL RESPONSE:")
        print(repr(response.content))

        content = response.content.strip()


        # -------------------------------------------------
        # Remove Markdown code fences
        # -------------------------------------------------

        if content.startswith("```"):

            content = content.removeprefix("```json")
            content = content.removeprefix("```")
            content = content.removesuffix("```")

            content = content.strip()


        # -------------------------------------------------
        # Try to parse JSON
        # -------------------------------------------------

        try:

            extraction_data = json.loads(content)

        except json.JSONDecodeError:

            # The free model sometimes returns non-JSON text.
            # Ask it one more time with stricter instructions.

            retry_messages = [
                {
                    "role": "system",
                    "content": MISSION_SYSTEM_PROMPT
                    + """

IMPORTANT:
Your previous response was not valid JSON.

Return ONLY a valid JSON object.
Do not write explanations outside the JSON.
Do not use Markdown.
Do not write "User Safety", "Analysis", or any other text.

The JSON must contain exactly these fields:

mission_type
priority
origin
destination
confidence
explanation

Allowed mission_type values:

TRAUMA
MEDICAL_SUPPLY
RESCUE
RELIEF

Allowed priority values:

CRITICAL
HIGH
NORMAL
""",
                },
                {
                    "role": "user",
                    "content": user_request,
                },
            ]

            retry_response = self.structured_model.invoke(
                retry_messages
            )

            print("\nRETRY MODEL RESPONSE:")
            print(repr(retry_response.content))

            content = retry_response.content.strip()


            # Remove Markdown code fences again
            if content.startswith("```"):

                content = content.removeprefix("```json")
                content = content.removeprefix("```")
                content = content.removesuffix("```")

                content = content.strip()


            extraction_data = json.loads(content)


        # -------------------------------------------------
        # Validate extracted mission
        # -------------------------------------------------

        extraction = MissionExtraction.model_validate(
            extraction_data
        )


        # -------------------------------------------------
        # Apply deterministic mission defaults
        # -------------------------------------------------

        defaults = MISSION_DEFAULTS[
            extraction.mission_type
        ]


        # -------------------------------------------------
        # Build final MissionProfile
        # -------------------------------------------------

        profile = MissionProfile(

            mission_type=extraction.mission_type,

            priority=extraction.priority,

            origin=extraction.origin,

            destination=extraction.destination,

            time_weight=defaults["time_weight"],

            safety_weight=defaults["safety_weight"],

            payload_sensitivity=defaults["payload_sensitivity"],

            confidence=extraction.confidence,

            explanation=extraction.explanation,
        )


        return profile
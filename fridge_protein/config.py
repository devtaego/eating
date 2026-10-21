import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
TITLE = "먹을 결심 🫪👅🧑‍🩰🐽🍤"


def load_settings():
    """Only three .env entries. Modes are selected in the UI, not the .env file."""
    load_dotenv(ROOT / ".env", override=False, encoding="utf-8-sig")
    return {"data_mode": "live" if os.getenv("DATA_GO_KR_SERVICE_KEY") else "sample",
            "model": os.getenv("OPENAI_DEFAULT_MODEL", "gpt-6-luna"),
            "has_food_key": bool(os.getenv("DATA_GO_KR_SERVICE_KEY")),
            "has_openai_key": bool(os.getenv("OPENAI_API_KEY"))}

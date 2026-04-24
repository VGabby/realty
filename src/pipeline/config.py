import os
from typing import Literal

from pydantic import BaseModel, ConfigDict


class RunConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    edit_model: str = "gemini-3.1-flash-image-preview"
    review_model: str = "gemini-3.1-flash-lite-preview"
    phase1_threshold: float = 7.0
    phase2_threshold: float = 8.0
    max_retries: dict[Literal["phase1", "phase2"], int] = {"phase1": 3, "phase2": 2}
    api_key_env: str = "GEMINI_API_KEY"
    aesthetic: Literal["mls_us", "jp_real_estate", "luxury"] = "mls_us"
    network_timeout: int = 60
    image_size: str | None = "512"

    @classmethod
    def from_env(cls) -> "RunConfig":
        """Read optional env var overrides; unset vars use defaults."""
        kwargs: dict = {}
        if v := os.environ.get("DECLUTTER_EDIT_MODEL"):
            kwargs["edit_model"] = v
        if v := os.environ.get("DECLUTTER_REVIEW_MODEL"):
            kwargs["review_model"] = v
        if v := os.environ.get("DECLUTTER_PHASE1_THRESHOLD"):
            kwargs["phase1_threshold"] = float(v)
        if v := os.environ.get("DECLUTTER_PHASE2_THRESHOLD"):
            kwargs["phase2_threshold"] = float(v)
        if v := os.environ.get("DECLUTTER_NETWORK_TIMEOUT"):
            kwargs["network_timeout"] = int(v)
        if v := os.environ.get("DECLUTTER_IMAGE_SIZE"):
            kwargs["image_size"] = v
        return cls(**kwargs)

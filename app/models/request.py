from pydantic import BaseModel, Field


class ScanRequest(BaseModel):
    address: str
    window_days: int = Field(default=90, ge=30, le=180, alias="windowDays")

    model_config = {"populate_by_name": True}

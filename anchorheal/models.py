import re
from pydantic import BaseModel, Field, model_validator
from typing import List, Dict, Optional, Tuple, Any
import datetime

class Anchor(BaseModel):
    caller_id: str = Field(..., description="Unique caller identifier (e.g., filename:lineno:selector or field name)")
    primary_selector: str = Field(..., description="The selector originally queried in the source code")
    confidence: float = Field(1.0, description="Current confidence rating [0.0, 1.0]")

    @model_validator(mode='before')
    @classmethod
    def map_text_to_pattern(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "text" in data and not data.get("text_pattern"):
                data["text_pattern"] = re.escape(data["text"])
        return data

    # DOM features
    tag: str
    classes: List[str] = Field(default_factory=list)
    id_attr: Optional[str] = None
    text_pattern: str = ""
    parent_chain: List[str] = Field(default_factory=list)
    sibling_text: List[str] = Field(default_factory=list)
    xpath: str = ""

    # Visual features
    rel_position: Optional[Dict[str, float]] = None # {"x_pct": float, "y_pct": float}
    bbox: Optional[Dict[str, float]] = None         # {"x": float, "y": float, "w": float, "h": float}
    viewport: Optional[Dict[str, float]] = None     # {"w": float, "h": float}
    crop_32: Optional[bytes] = None
    crop_64: Optional[bytes] = None

class ConfidenceHistoryEntry(BaseModel):
    caller_id: str
    timestamp: datetime.datetime
    confidence: float

class HealEvent(BaseModel):
    caller_id: str
    timestamp: datetime.datetime
    old_selector: str
    new_selector: str
    healed_features: Dict
    confidence_before: float
    confidence_after: float
    primary_winning_signal: str # "dom", "visual", "text", "context"

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ParsedAction:
    action: str
    item_name: str
    quantity: float
    unit: str
    purpose: str
    destination: str
    raw_input: str
    confidence: float = 0.8
    extra: Optional[Dict[str, Any]] = field(default_factory=dict)

"""
Models module for Prometheus.
Data models and validation schemas.
"""

from dataclasses import dataclass, field
from typing import Optional, List
from datetime import datetime


@dataclass
class Item:
    """Represents an inventory item."""
    item_id: str
    item_name: str
    unit: str = "pcs"
    starting_stock: float = 0
    current_stock: float = 0
    used: float = 0
    purpose: str = ""
    wipro_in: float = 0
    wipro_out: float = 0
    rajagiri_main: float = 0
    woods: float = 0
    garden_cafe: float = 0
    bba_canteen: float = 0
    bba_tea_counter: float = 0
    purchased: float = 0
    damaged: float = 0
    avg_daily_usage: float = 0
    location: str = ""
    category: str = ""
    last_updated: Optional[str] = None
    last_updated_by: str = ""
    working_date: Optional[str] = None


@dataclass
class Transaction:
    """Represents a stock transaction."""
    item_id: str
    item_name: str
    action: str
    quantity: float
    unit: str
    stock_before: float
    stock_after: float
    timestamp: str = ""
    date: str = ""
    purpose: str = ""
    destination: str = ""
    performed_by: str = ""
    notes: str = ""


@dataclass
class UndoEntry:
    """Represents an undo log entry."""
    item_id: str
    action: str
    quantity: float
    stock_before: float
    stock_after: float
    timestamp: str = ""
    transaction_id: Optional[int] = None
    details: str = ""
    performed_by: str = ""
    reversed: bool = False


@dataclass
class ParsedAction:
    """Represents a parsed action from AI or command input."""
    action: str  # e.g. 'used', 'purchased', 'damaged'
    item_name: str
    quantity: float
    unit: str = ""
    purpose: str = ""
    destination: str = ""
    raw_input: str = ""
    confidence: float = 1.0

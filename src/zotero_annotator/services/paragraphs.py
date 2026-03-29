from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ParagraphCoord:
    page: int
    x: float
    y: float
    w: float
    h: float


@dataclass
class Paragraph:
    text: str
    hash: str
    dedup_hashes: List[str]
    coords: List[ParagraphCoord]
    page: Optional[int]

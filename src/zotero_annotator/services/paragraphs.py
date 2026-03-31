from __future__ import annotations

from dataclasses import dataclass


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
    dedup_hashes: list[str]
    coords: list[ParagraphCoord]
    page: int | None

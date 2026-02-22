from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from typing import List, Optional

from defusedxml import ElementTree as ET


# Data class for paragraph coordinates (段落の座標を表すデータクラス)
@dataclass
class ParagraphCoord:
    page: int
    x: float
    y: float
    w: float
    h: float


# Data class for paragraph content (段落の本文を表すデータクラス)
@dataclass
class Paragraph:
    text: str
    hash: str
    coords: List[ParagraphCoord]
    page: Optional[int]

# Normalize whitespace for stable hashing/dedup (空白を正規化して重複判定を安定化)
def _normalize_text(text: str) -> str:
    return " ".join(text.split()).strip()

# SHA1 hash computation function (SHA1ハッシュ計算関数(重複判定タグ))
def _sha1(text: str) -> str:
    return sha1(text.encode("utf-8")).hexdigest()

# Extract local name from XML tag (XMLタグからローカル名を抽出)
def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag

# Find coords attribute in an element (要素からcoords属性を探す)
def _find_coords_attr(elem: ET.Element) -> Optional[str]:
    for key, value in elem.attrib.items():
        if _local_name(key) == "coords":
            return value
    return None

# Parse coords string "page,x,y,w,h;..." into ParagraphCoord list (座標文字列 "page,x,y,w,h;..." を ParagraphCoord のリストに変換する)
def _parse_coords(coords_str: str) -> List[ParagraphCoord]:
    coords: List[ParagraphCoord] = []
    if not coords_str:
        return coords
    for part in coords_str.split(";"):
        bits = [b.strip() for b in part.split(",") if b.strip() != ""]
        if len(bits) != 5:
            continue
        try:
            page = int(float(bits[0]))
            x = float(bits[1])
            y = float(bits[2])
            w = float(bits[3])
            h = float(bits[4])
        except ValueError:
            continue
        coords.append(ParagraphCoord(page=page, x=x, y=y, w=w, h=h))
    return coords

# Extract paragraphs and optional coordinates from TEI XML (TEIから段落と座標を抽出)
def extract_paragraphs(tei_xml: str, min_chars: int, max_chars: int) -> List[Paragraph]:
    try:
        root = ET.fromstring(tei_xml)
    except ET.ParseError as exc:
        raise ValueError("Invalid TEI XML") from exc
    paragraphs: List[Paragraph] = []

    for elem in root.iter():
        if _local_name(elem.tag) != "p":
            continue
        raw_text = "".join(elem.itertext())
        text = _normalize_text(raw_text)
        if not text:
            continue
        if len(text) < min_chars:
            continue
        if len(text) > max_chars:
            #TODO For now keep the full text; downstream can split if needed.
            pass
        coords_str = _find_coords_attr(elem)
        coords = _parse_coords(coords_str) if coords_str else []
        page = coords[0].page if coords else None
        paragraphs.append(
            Paragraph(
                text=text,
                hash=_sha1(text),
                coords=coords,
                page=page,
            )
        )

    return paragraphs

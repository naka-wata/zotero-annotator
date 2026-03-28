from __future__ import annotations

from typing import Any, Dict, List, NotRequired, TypedDict


class ZoteroTag(TypedDict):
    """Zotero tag object used inside items and annotations."""

    tag: str


class ZoteroItemData(TypedDict, total=False):
    """
    ``data`` field of a Zotero item (journal article, book, etc.).

    Fields are marked as NotRequired because attachment items may omit
    ``title``, and the subset of fields varies by ``itemType``.
    """

    key: str
    itemType: str
    title: str
    tags: List[ZoteroTag]
    # Attachment-specific
    contentType: str
    parentItem: str


class ZoteroItem(TypedDict, total=False):
    """Top-level Zotero item as returned by the Web API (``include=data``)."""

    key: str
    version: int
    data: ZoteroItemData
    links: Dict[str, Any]


class ZoteroAnnotationData(TypedDict, total=False):
    """
    ``data`` field of a Zotero annotation item.

    Several fields (annotationPosition / annotationPageLabel /
    annotationSortIndex) are marked as NotRequired because they can be
    missing in "broken" annotations that the repair/delete helpers handle.
    """

    key: str
    itemType: str  # always "annotation" for annotations
    parentItem: str
    annotationType: str  # "note" or "highlight"
    # Body field: annotationComment is used for annotation items,
    # note is the fallback for legacy / note-type items.
    annotationComment: str
    note: str
    # Position fields (may be absent in broken annotations)
    annotationPosition: str  # JSON-encoded string
    annotationPageLabel: str
    annotationSortIndex: str
    tags: List[ZoteroTag]


class ZoteroAnnotation(TypedDict, total=False):
    """Top-level Zotero annotation item as returned by the Web API."""

    key: str
    version: int
    data: ZoteroAnnotationData
    links: Dict[str, Any]

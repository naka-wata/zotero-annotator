from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import httpx


class ZoteroClient:
    def __init__(self, base_url: str, api_key: str, scope: str, library_id: str, timeout_seconds: int = 30, ) -> None:
        self.base_url = base_url.rstrip("/")                 # Zotero API base URL (zoteroのAPIのベースURL)
        self.api_key = api_key                               # Zotero API key (zoteroのAPIキー)
        self.scope = scope                                   # Zotero library scope, either "user" or "group" (zoteroのライブラリのスコープ、"user"または"group")
        self.library_id = library_id                         # Zotero library ID (zoteroの ユーザー or グループ ID)
        self.timeout_seconds = timeout_seconds               # HTTP request timeout in seconds (HTTPリクエストのタイムアウト時間（秒）)
        self._client = httpx.Client(timeout=timeout_seconds) # HTTP client instance (HTTPクライアントのインスタンス)

    def close(self) -> None:
        self._client.close()

    # Internal method to build headers for API requests (APIリクエスト用のヘッダーを作成する)
    def _headers(self) -> dict[str, str]:
        return {
            "Zotero-API-Key": self.api_key,
            "Zotero-API-Version": "3",
        }

    # Internal method to get the library path based on scope and library ID (スコープとライブラリIDに基づいてライブラリパスを取得する)
    def _library_path(self) -> str:
        if self.scope == "user":
            return f"users/{self.library_id}"
        return f"groups/{self.library_id}"


    # Internal method to perform GET requests (GETリクエストを実行する)
    def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        return self._client.get(url, headers=self._headers(), params=params)

    # Internal method to perform POST requests (POSTリクエストを実行する)
    def _post(self, path: str, json_body: Any) -> httpx.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        return self._client.post(url, headers=self._headers(), json=json_body)

    # Internal method to perform PUT requests (PUTリクエストを実行する)
    def _put(self, path: str, json_body: Any, headers: dict[str, str] | None = None) -> httpx.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        merged = self._headers()
        if headers:
            merged.update(headers)
        return self._client.put(url, headers=merged, json=json_body)

    # Internal method to perform DELETE requests (DELETEリクエストを実行する)
    def _delete(self, path: str, headers: dict[str, str] | None = None) -> httpx.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        merged = self._headers()
        if headers:
            merged.update(headers)
        return self._client.delete(url, headers=merged)

    # List items by tag (タグのついた論文をリストする)
    def list_items_by_tag(self, tag: str, limit: int = 25, start: int = 0) -> list[dict[str, Any]]:
        params = {
            "include": "data",
            "limit": limit,
            "start": start,
            "tag": tag,
        }
        resp = self._get(f"{self._library_path()}/items", params=params)
        resp.raise_for_status()
        return resp.json()

    # Iterate over all items by tag with pagination (タグのついた論文をlist_items_by_tagで繰り返し取得する)
    def iter_items_by_tag(self, tag: str, limit_per_page: int = 100) -> Iterable[dict[str, Any]]:
        start = 0
        while True:
            items = self.list_items_by_tag(tag=tag, limit=limit_per_page, start=start)
            if not items:
                break
            yield from items
            start += len(items)

    # List children items of a parent item (親アイテムの子アイテム(pdfやスナップショット)をリストする)
    def list_children(self, parent_key: str) -> list[dict[str, Any]]:
        params = {"include": "data"}
        resp = self._get(f"{self._library_path()}/items/{parent_key}/children", params=params)
        resp.raise_for_status()
        return resp.json()

    # Get a single item by key (アイテムをキーで取得する)
    def get_item(self, item_key: str) -> dict[str, Any]:
        params = {"include": "data"}
        resp = self._get(f"{self._library_path()}/items/{item_key}", params=params)
        resp.raise_for_status()
        return resp.json()

    # Pick the first PDF attachment from children items (list_childrenの子アイテムの中から最初のPDF添付ファイルを選択する)
    def pick_pdf_attachment(self, children: list[dict[str, Any]]) -> dict[str, Any] | None:
        for item in children:
            content_type = (item.get("data") or {}).get("contentType") or ""
            if "pdf" in content_type.lower():
                return item
        return None

    # Build file download URL for an attachment (添付ファイル(PDF)のダウンロードURLを作成する)
    def build_file_url(self, attachment_key: str) -> str:
        return f"{self.base_url}/{self._library_path()}/items/{attachment_key}/file"

    # Download attachment file content (論文PDFをダウンロードする)
    def download_attachment(self, file_url: str) -> bytes:
        # Zotero file endpoint returns 302 to S3; follow redirect to fetch bytes.
        resp = self._client.get(file_url, headers=self._headers(), follow_redirects=True)
        resp.raise_for_status()
        return resp.content

    # List annotations for a parent item (親アイテムの 注釈:annotation をリストする)
    def list_annotations(self, parent_key: str, *, limit: int = 100, start: int = 0) -> list[dict[str, Any]]:
        params = {
            "include": "data",
            "format": "json",
            "limit": limit,
            "start": start,
        }
        # Use children endpoint to guarantee parent scoping for this attachment.
        # (parentItem クエリ依存を避け、親添付配下の子アイテムのみ取得する)
        resp = self._get(f"{self._library_path()}/items/{parent_key}/children", params=params)
        resp.raise_for_status()
        items = resp.json()
        return [i for i in items if (i.get("data") or {}).get("itemType") == "annotation"]

    # Iterate over all annotations with pagination (注釈をページングしながら全件取得する)
    def iter_annotations(self, parent_key: str, limit_per_page: int = 100) -> Iterable[dict[str, Any]]:
        start = 0
        while True:
            items = self.list_annotations(parent_key=parent_key, limit=limit_per_page, start=start)
            if not items:
                break
            yield from items
            start += len(items)

    # Create annotations (注釈:annotation を作成する)
    def create_annotations(self, annotations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        resp = self._post(f"{self._library_path()}/items", json_body=annotations)
        resp.raise_for_status()
        return resp.json()

    # Update an item with concurrency control (アイテムを安全に更新する)
    def update_item(self, item_key: str, data: dict[str, Any], version: int | None) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if version is not None:
            headers["If-Unmodified-Since-Version"] = str(version)
        resp = self._put(f"{self._library_path()}/items/{item_key}", json_body=data, headers=headers)
        resp.raise_for_status()
        # Zotero update endpoints can return 204 No Content on success.
        # (Zoteroの更新APIは成功時に204でボディなしの場合がある)
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    # Delete an item with concurrency control (アイテムを安全に削除する)
    def delete_item(self, item_key: str, version: int | None) -> None:
        headers: dict[str, str] = {}
        if version is not None:
            headers["If-Unmodified-Since-Version"] = str(version)
        resp = self._delete(f"{self._library_path()}/items/{item_key}", headers=headers)
        resp.raise_for_status()

    # Update item tags safely (アイテムのタグを安全に更新する)
    def update_item_tags(self, item_key: str, tags: list[str]) -> dict[str, Any]:
        item = self.get_item(item_key)
        data = dict(item.get("data") or {})
        data["tags"] = [{"tag": t} for t in tags]
        version = item.get("version")
        return self.update_item(item_key, data, version)

    # Extract tag names from an item (アイテムからタグ名を抽出する)
    @staticmethod
    def extract_tag_names(item: dict[str, Any]) -> list[str]:
        tags = (item.get("data") or {}).get("tags") or []
        return [t.get("tag") for t in tags if isinstance(t, dict) and t.get("tag")]

    # Merge current tags with additions and removals (現在のタグに追加と削除を反映させる)
    @staticmethod
    def merge_tags(current: list[str], add: Iterable[str], remove: Iterable[str]) -> list[str]:
        next_tags = set(current)
        next_tags.update(t for t in add if t)
        next_tags.difference_update(t for t in remove if t)
        return sorted(next_tags)

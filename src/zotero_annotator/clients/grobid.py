from __future__ import annotations

from typing import Optional

import httpx


class GrobidClient:
    def __init__(self, base_url: str, timeout_seconds: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._client = httpx.Client(timeout=timeout_seconds)

    def close(self) -> None:
        self._client.close()

    # Process fulltext PDF and return TEI XML (フルテキストPDFを処理してTEI XMLを返す)
    def process_fulltext(self, pdf_bytes: bytes, tei_coordinates: str = "p") -> str:
        url = f"{self.base_url}/api/processFulltextDocument"
        files = {"input": ("document.pdf", pdf_bytes, "application/pdf")}
        data = {
            "consolidateHeader": "1",
            "consolidateCitations": "1",
            "teiCoordinates": tei_coordinates,
        }
        resp = self._client.post(url, files=files, data=data)
        resp.raise_for_status()
        return resp.text

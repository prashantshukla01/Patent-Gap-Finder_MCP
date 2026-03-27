"""Async EPO Open Patent Services (OPS) client.

Handles OAuth 2.0 token management, CQL query construction, and
response parsing.  Gracefully skips when credentials are missing.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ── Custom exceptions ────────────────────────────────────────────────


class EPOAuthError(Exception):
    """OAuth token acquisition failed."""


class EPOQuotaError(Exception):
    """EPO weekly data quota exceeded."""


class EPOParseError(Exception):
    """Failed to parse EPO response."""


# ── Client ───────────────────────────────────────────────────────────

AUTH_URL = "https://ops.epo.org/3.2/auth/accesstoken"
SEARCH_URL = "https://ops.epo.org/3.2/rest-services/published-data/search"
BIBLIO_URL = "https://ops.epo.org/3.2/rest-services/published-data/publication/epodoc"

# Rate limit: 10 req/sec → 3 concurrent + 0.35s gap
_semaphore = asyncio.Semaphore(3)


class EPOClient:
    """EPO OPS client with OAuth 2.0 token management."""

    def __init__(self) -> None:
        self._consumer_key = os.environ.get("EPO_CONSUMER_KEY", "")
        self._consumer_secret = os.environ.get("EPO_CONSUMER_SECRET", "")
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

    def is_available(self) -> bool:
        """Check whether EPO credentials are configured."""
        return bool(self._consumer_key and self._consumer_secret)

    async def _ensure_token(self, client: httpx.AsyncClient) -> str:
        """Fetch or refresh OAuth token if needed.

        Returns the current access token.
        """
        now = datetime.now(timezone.utc)

        if (
            self._access_token
            and self._token_expires_at
            and (self._token_expires_at - now).total_seconds() > 60
        ):
            return self._access_token

        credentials = base64.b64encode(
            f"{self._consumer_key}:{self._consumer_secret}".encode()
        ).decode()

        try:
            response = await client.post(
                AUTH_URL,
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data="grant_type=client_credentials",
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise EPOAuthError(f"EPO auth failed: {e.response.status_code}") from e

        token_data = response.json()
        self._access_token = token_data["access_token"]
        expires_in = int(token_data.get("expires_in", 1200))
        self._token_expires_at = now + __import__("datetime").timedelta(seconds=expires_in)
        logger.info("EPO OAuth token acquired (expires in %ds)", expires_in)
        return self._access_token

    def _build_cql(self, keywords: list[str], ipc_codes: list[str]) -> str:
        """Build a CQL query string for EPO search.

        Limits to 5 keywords to stay within EPO query length limits.
        Uses section+class prefix for IPC filtering (e.g. "G06N").
        """
        parts = []

        if keywords:
            terms = " AND ".join(keywords[:5])
            parts.append(f"txt=({terms})")

        if ipc_codes:
            prefixes = list({code.split()[0] for code in ipc_codes if code.strip()})
            if prefixes:
                parts.append(f"ic={prefixes[0]}")

        if not parts:
            raise ValueError("At least one of keywords or ipc_codes required")

        return " AND ".join(parts)

    async def search(
        self,
        keywords: list[str],
        ipc_codes: list[str],
        max_results: int = 100,
    ) -> list[dict]:
        """Search EPO OPS and return raw patent dicts.

        Args:
            keywords: Search terms for full-text search.
            ipc_codes: IPC codes for filtering.
            max_results: Maximum patents to return.

        Returns:
            List of parsed patent dicts.
        """
        if not self.is_available():
            logger.warning("EPO credentials not configured — skipping EPO search")
            return []

        cql = self._build_cql(keywords, ipc_codes)
        all_patents: list[dict] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            token = await self._ensure_token(client)

            page_start = 1
            page_size = 50

            while len(all_patents) < max_results:
                page_end = min(page_start + page_size - 1, max_results)
                range_header = f"{page_start}-{page_end}"

                async with _semaphore:
                    try:
                        response = await self._search_page(
                            client, cql, range_header, token
                        )
                    except EPOAuthError:
                        # Token might have expired mid-search — refresh and retry once
                        self._access_token = None
                        token = await self._ensure_token(client)
                        response = await self._search_page(
                            client, cql, range_header, token
                        )
                    await asyncio.sleep(0.35)

                patents = self._parse_search_response(response)
                if not patents:
                    break

                all_patents.extend(patents)
                logger.info(
                    "EPO page %s: %d publications", range_header, len(patents)
                )

                if len(patents) < page_size:
                    break
                page_start += page_size

        return all_patents[:max_results]

    async def _search_page(
        self,
        client: httpx.AsyncClient,
        cql: str,
        range_header: str,
        token: str,
    ) -> dict:
        """Execute a single EPO search request."""
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "X-OPS-Range": range_header,
        }

        response = await client.get(
            SEARCH_URL,
            params={"q": cql},
            headers=headers,
        )

        if response.status_code == 401:
            raise EPOAuthError("Token expired")
        if response.status_code == 403:
            raise EPOQuotaError("EPO weekly data quota exceeded")
        if response.status_code == 404:
            return {}
        response.raise_for_status()

        return response.json()

    def _parse_search_response(self, data: dict) -> list[dict]:
        """Parse EPO search JSON into list of patent dicts.

        Handles the notorious single-result vs array-of-results
        difference in EPO responses.
        """
        if not data:
            return []

        try:
            search_result = (
                data.get("ops:world-patent-data", {})
                .get("ops:biblio-search", {})
                .get("ops:search-result", {})
            )

            refs = search_result.get("ops:publication-reference", [])

            # EPO wraps single results as dict, multiple as list
            if isinstance(refs, dict):
                refs = [refs]

            patents = []
            for ref in refs:
                doc_id = ref.get("document-id", {})
                if isinstance(doc_id, list):
                    doc_id = doc_id[0] if doc_id else {}

                country = doc_id.get("country", {})
                if isinstance(country, dict):
                    country = country.get("$", "")

                doc_number = doc_id.get("doc-number", {})
                if isinstance(doc_number, dict):
                    doc_number = doc_number.get("$", "")

                kind = doc_id.get("kind", {})
                if isinstance(kind, dict):
                    kind = kind.get("$", "")

                if country and doc_number:
                    patents.append({
                        "country": country,
                        "doc_number": doc_number,
                        "kind": kind,
                        "publication_number": f"{country}{doc_number}{kind}",
                    })

            return patents

        except Exception as e:
            logger.warning("EPO response parse error: %s", e)
            return []


# ── Module-level singleton ───────────────────────────────────────────

_epo_client: Optional[EPOClient] = None


def get_epo_client() -> EPOClient:
    """Return the EPO client singleton."""
    global _epo_client
    if _epo_client is None:
        _epo_client = EPOClient()
    return _epo_client


def reset_epo_client() -> None:
    """Reset singleton (for tests)."""
    global _epo_client
    _epo_client = None

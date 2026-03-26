import logging

import httpx

logger = logging.getLogger(__name__)


async def fetch_page(url: str, headers: dict) -> str:
    """Fetch a page, falling back to curl_cffi on 403."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers=headers, follow_redirects=True, timeout=30.0,
            )
            response.raise_for_status()
            return response.text
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            logger.info("Got 403 from %s, retrying with curl_cffi", url)
            from curl_cffi.requests import AsyncSession

            async with AsyncSession() as s:
                # Don't pass custom headers — let curl_cffi's browser
                # impersonation set its own consistent TLS + header fingerprint.
                r = await s.get(
                    url, impersonate="chrome", timeout=30,
                )
                r.raise_for_status()
                return r.text
        raise

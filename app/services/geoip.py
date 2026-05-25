"""GeoIP lookup via ip-api.com (free, no key needed, 45 req/min)."""
import logging
import httpx

logger = logging.getLogger(__name__)

_cache = {}  # Simple in-memory cache: ip -> {city, timezone, region}


async def lookup_ip(ip: str) -> dict:
    """Returns {city, timezone, region, country} or empty dict on error."""
    if not ip or ip in ("127.0.0.1", "localhost", "::1"):
        return {}

    # Strip docker proxy IPs
    if ip.startswith("172.") or ip.startswith("10."):
        return {}

    if ip in _cache:
        return _cache[ip]

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"http://ip-api.com/json/{ip}",
                params={"fields": "city,regionName,timezone,country", "lang": "ru"}
            )
            if resp.status_code == 200:
                data = resp.json()
                result = {
                    "city": data.get("city", ""),
                    "timezone": data.get("timezone", ""),
                    "region": data.get("regionName", ""),
                    "country": data.get("country", ""),
                }
                _cache[ip] = result
                # Keep cache small
                if len(_cache) > 1000:
                    _cache.clear()
                return result
    except Exception as e:
        logger.warning("GeoIP lookup failed for %s: %s", ip, e)

    return {}

from __future__ import annotations

import asyncio
import math

import httpx
import structlog

from properties.application.ports.places_service import PlacesService
from properties.domain.models.nearby_place import (
    GOOGLE_MAPS_PLACE_URL,
    NearbyPlace,
    PlaceDetails,
)

log = structlog.get_logger()

NEARBY_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
PLACE_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
PHOTO_URL = "https://maps.googleapis.com/maps/api/place/photo"

# Per spec 2026-05-poi-rich-metadata: hard caps so the persisted JSONB
# columns stay small and a malicious / abusive Google response can't
# blow up our row size.
MAX_IMAGES_PER_POI = 5
MAX_REVIEWS_PER_POI = 5
PHOTO_MAX_WIDTH = 800

# Google Nearby Search returns up to 20 results per page, with at most
# three pages (60 results total) chained via `next_page_token`. The
# token isn't immediately valid — Google's docs require a short delay
# before the follow-up request. We pause `NEXT_PAGE_TOKEN_DELAY_S`
# between pages so the second/third call doesn't 400 with INVALID_REQUEST.
MAX_NEARBY_PAGES = 3
NEXT_PAGE_TOKEN_DELAY_S = 2.0

# Fields we actually use from a review object — anything else (user IDs,
# profile photo URLs) is dropped before persisting.
_REVIEW_FIELDS_KEEP = ("author_name", "rating", "text", "time", "language")


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in meters between two points using haversine formula."""
    r = 6_371_000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class GooglePlacesService(PlacesService):
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def find_nearby(
        self,
        latitude: float,
        longitude: float,
        place_type: str,
        radius_meters: int = 5000,
        keyword: str | None = None,
    ) -> list[NearbyPlace]:
        """Run a Nearby Search and follow `next_page_token` up to
        `MAX_NEARBY_PAGES`. Pagination keeps the public port shape but
        lets municipality-wide policies see more than the first 20.
        """
        base_params: dict[str, str | int] = {
            "location": f"{latitude},{longitude}",
            "radius": radius_meters,
            "type": place_type,
            "key": self._api_key,
        }
        if keyword:
            base_params["keyword"] = keyword

        places: list[NearbyPlace] = []
        next_page_token: str | None = None

        async with httpx.AsyncClient(timeout=30) as client:
            for page_index in range(MAX_NEARBY_PAGES):
                params: dict[str, str | int] = (
                    {"pagetoken": next_page_token, "key": self._api_key}
                    if next_page_token
                    else dict(base_params)
                )
                if page_index > 0:
                    # Google rejects the token if used too quickly.
                    await asyncio.sleep(NEXT_PAGE_TOKEN_DELAY_S)

                try:
                    response = await client.get(NEARBY_SEARCH_URL, params=params)
                    response.raise_for_status()
                    data = response.json()
                except Exception:
                    log.exception(
                        "google_places.request_failed",
                        place_type=place_type,
                        keyword=keyword,
                        page_index=page_index,
                    )
                    break

                status = data.get("status")
                if status not in ("OK", "ZERO_RESULTS"):
                    log.warning(
                        "google_places.api_error",
                        status=status,
                        error_message=data.get("error_message"),
                        page_index=page_index,
                    )
                    break

                places.extend(
                    self._parse_results(
                        data.get("results", []),
                        origin_lat=latitude,
                        origin_lng=longitude,
                    )
                )

                next_page_token = data.get("next_page_token")
                if not next_page_token:
                    break

        log.info(
            "google_places.search_completed",
            place_type=place_type,
            keyword=keyword,
            results_count=len(places),
        )
        return places

    @staticmethod
    def _parse_results(
        raw_results: list[dict],
        *,
        origin_lat: float,
        origin_lng: float,
    ) -> list[NearbyPlace]:
        parsed: list[NearbyPlace] = []
        for result in raw_results:
            location = result.get("geometry", {}).get("location", {})
            place_lat = location.get("lat")
            place_lng = location.get("lng")
            name = result.get("name", "")
            place_id = result.get("place_id")

            if place_lat is None or place_lng is None or not name:
                continue

            distance = _haversine_distance(origin_lat, origin_lng, place_lat, place_lng)
            google_maps_url = GOOGLE_MAPS_PLACE_URL.format(place_id=place_id) if place_id else None
            parsed.append(
                NearbyPlace(
                    name=name,
                    distance_meters=round(distance, 1),
                    latitude=place_lat,
                    longitude=place_lng,
                    place_id=place_id,
                    google_maps_url=google_maps_url,
                    vicinity=result.get("vicinity"),
                )
            )
        return parsed

    async def get_place_details(
        self,
        place_id: str,
        *,
        include_reviews: bool = True,
    ) -> PlaceDetails | None:
        """Fetch rich place metadata. Returns `None` on any failure.

        Cost-aware `fields=` filter (spec §Reviews blacklist): when
        `include_reviews=False` we don't request `reviews`, so Google
        doesn't bill us for the atmosphere SKU.
        """
        # Build a minimal `fields=` to avoid paying for data we don't use.
        fields = ["formatted_address", "photos"]
        if include_reviews:
            fields.append("reviews")

        params: dict[str, str] = {
            "place_id": place_id,
            "fields": ",".join(fields),
            "key": self._api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(PLACE_DETAILS_URL, params=params)
                response.raise_for_status()
                data = response.json()
        except Exception:
            log.exception("google_places.details_request_failed", place_id=place_id)
            return None

        status = data.get("status")
        if status not in ("OK",):
            log.warning(
                "google_places.details_api_error",
                place_id=place_id,
                status=status,
                error_message=data.get("error_message"),
            )
            return None

        result = data.get("result") or {}
        formatted_address = result.get("formatted_address")

        photo_refs = [
            p.get("photo_reference")
            for p in (result.get("photos") or [])[:MAX_IMAGES_PER_POI]
            if p.get("photo_reference")
        ]
        image_urls: list[str] = []
        if photo_refs:
            try:
                image_urls = await self._resolve_photo_urls(photo_refs)
            except Exception:
                log.exception("google_places.photo_resolution_aborted", place_id=place_id)
                image_urls = []

        reviews: list[dict] | None = None
        if include_reviews:
            raw_reviews = result.get("reviews") or []
            reviews = [
                {k: r.get(k) for k in _REVIEW_FIELDS_KEEP if k in r}
                for r in raw_reviews[:MAX_REVIEWS_PER_POI]
            ]

        return PlaceDetails(
            place_id=place_id,
            address=formatted_address,
            image_urls=image_urls,
            reviews=reviews,
        )

    async def _resolve_photo_urls(self, photo_references: list[str]) -> list[str]:
        """Each Photos API call returns a 302 to the resolved CDN URL.
        We follow the redirect manually (HEAD-then-Location) instead of
        downloading the photo bytes — saves bandwidth, gives us a
        renderable URL.
        """
        urls: list[str] = []
        async with httpx.AsyncClient(follow_redirects=False, timeout=15) as client:
            for ref in photo_references:
                try:
                    resp = await client.get(
                        PHOTO_URL,
                        params={
                            "maxwidth": PHOTO_MAX_WIDTH,
                            "photoreference": ref,
                            "key": self._api_key,
                        },
                    )
                except Exception:
                    log.exception("google_places.photo_redirect_failed")
                    continue

                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location")
                    if location:
                        urls.append(location)
                        continue

                # Non-redirect response (e.g. 404) → skip this photo,
                # don't abort the whole batch.
                log.warning(
                    "google_places.photo_unexpected_status",
                    status_code=resp.status_code,
                )
        return urls

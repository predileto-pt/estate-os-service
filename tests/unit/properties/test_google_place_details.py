"""Unit tests for GooglePlacesService.get_place_details.

Spec: 2026-05-poi-rich-metadata. Asserts:
- HTTP-level cost-aware contract: blacklisted categories don't request
  `reviews` from Google.
- Photo redirect resolution: 302 → Location header; partial failures
  skip the bad photo without aborting the batch.
- Failure modes return None (never raise).
- Review trimming drops fields we don't render.
"""

from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from properties.adapters.places.google_places_service import GooglePlacesService


def _mock_transport(handler):
    """Build an httpx.MockTransport delegating each request to `handler`."""
    return httpx.MockTransport(handler)


@pytest.fixture
def patch_httpx_client(monkeypatch):
    """Patch httpx.AsyncClient so adapter calls hit our handler."""

    def install(handler):
        original_init = httpx.AsyncClient.__init__

        def _patched_init(self, *args, **kwargs):
            kwargs["transport"] = _mock_transport(handler)
            original_init(self, *args, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "__init__", _patched_init)

    return install


async def test_fields_filter_includes_reviews_by_default(patch_httpx_client):
    """Default `include_reviews=True` → outbound URL has fields=...,reviews."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path == "/maps/api/place/details/json":
            return httpx.Response(
                200,
                json={
                    "status": "OK",
                    "result": {"formatted_address": "X", "photos": [], "reviews": []},
                },
            )
        return httpx.Response(404)

    patch_httpx_client(handler)
    svc = GooglePlacesService(api_key="K")
    details = await svc.get_place_details("p1")
    assert details is not None

    details_call = next(r for r in captured if "details" in str(r.url.path))
    fields = parse_qs(urlparse(str(details_call.url)).query)["fields"][0]
    assert "reviews" in fields.split(",")


async def test_fields_filter_excludes_reviews_when_blacklisted(patch_httpx_client):
    """include_reviews=False (blacklisted category) → outbound URL must
    NOT have reviews in fields=. This is the cost saver."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "result": {"formatted_address": "Y", "photos": []},
            },
        )

    patch_httpx_client(handler)
    svc = GooglePlacesService(api_key="K")
    await svc.get_place_details("hospital-1", include_reviews=False)

    details_call = next(r for r in captured if "details" in str(r.url.path))
    fields = parse_qs(urlparse(str(details_call.url)).query)["fields"][0]
    assert "reviews" not in fields.split(",")
    assert "formatted_address" in fields.split(",")
    assert "photos" in fields.split(",")


async def test_photo_redirect_partial_failure(patch_httpx_client):
    """Three photos, photo #2's redirect 404s. Result must contain the
    two successful URLs, not three (and no exception)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/maps/api/place/details/json":
            return httpx.Response(
                200,
                json={
                    "status": "OK",
                    "result": {
                        "formatted_address": "Z",
                        "photos": [
                            {"photo_reference": "ref1"},
                            {"photo_reference": "ref2"},
                            {"photo_reference": "ref3"},
                        ],
                        "reviews": [],
                    },
                },
            )
        if request.url.path == "/maps/api/place/photo":
            ref = parse_qs(urlparse(str(request.url)).query)["photoreference"][0]
            if ref == "ref2":
                return httpx.Response(404)
            return httpx.Response(
                302,
                headers={"Location": f"https://lh3.googleusercontent.com/{ref}"},
            )
        return httpx.Response(404)

    patch_httpx_client(handler)
    svc = GooglePlacesService(api_key="K")
    details = await svc.get_place_details("p2")
    assert details is not None
    assert details.image_urls == [
        "https://lh3.googleusercontent.com/ref1",
        "https://lh3.googleusercontent.com/ref3",
    ]


async def test_review_trimming_keeps_only_render_fields(patch_httpx_client):
    """Review objects must be trimmed to author_name/rating/text/time/
    language; drop user IDs and profile photo URLs."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "result": {
                    "formatted_address": "A",
                    "photos": [],
                    "reviews": [
                        {
                            "author_name": "Ana",
                            "author_url": "https://drop.me",
                            "profile_photo_url": "https://drop.me/2",
                            "rating": 5,
                            "text": "Excelente!",
                            "time": 1700000000,
                            "language": "pt",
                        }
                    ],
                },
            },
        )

    patch_httpx_client(handler)
    svc = GooglePlacesService(api_key="K")
    details = await svc.get_place_details("p3")
    assert details is not None
    assert details.reviews == [
        {
            "author_name": "Ana",
            "rating": 5,
            "text": "Excelente!",
            "time": 1700000000,
            "language": "pt",
        }
    ]


async def test_review_hard_cap_5(patch_httpx_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "result": {
                    "formatted_address": "A",
                    "photos": [],
                    "reviews": [
                        {"author_name": f"r{i}", "rating": 4, "text": "ok", "time": i}
                        for i in range(10)
                    ],
                },
            },
        )

    patch_httpx_client(handler)
    svc = GooglePlacesService(api_key="K")
    details = await svc.get_place_details("p4")
    assert details is not None
    assert len(details.reviews) == 5


async def test_image_hard_cap_5(patch_httpx_client):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/maps/api/place/details/json":
            return httpx.Response(
                200,
                json={
                    "status": "OK",
                    "result": {
                        "formatted_address": "A",
                        "photos": [{"photo_reference": f"r{i}"} for i in range(10)],
                        "reviews": [],
                    },
                },
            )
        if request.url.path == "/maps/api/place/photo":
            ref = parse_qs(urlparse(str(request.url)).query)["photoreference"][0]
            return httpx.Response(302, headers={"Location": f"https://cdn/{ref}"})
        return httpx.Response(404)

    patch_httpx_client(handler)
    svc = GooglePlacesService(api_key="K")
    details = await svc.get_place_details("p5")
    assert details is not None
    assert len(details.image_urls) == 5


async def test_http_error_returns_none(patch_httpx_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    patch_httpx_client(handler)
    svc = GooglePlacesService(api_key="K")
    details = await svc.get_place_details("p6")
    assert details is None


async def test_status_not_ok_returns_none(patch_httpx_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "INVALID_REQUEST"})

    patch_httpx_client(handler)
    svc = GooglePlacesService(api_key="K")
    details = await svc.get_place_details("p7")
    assert details is None


async def test_missing_photos_and_reviews_yields_empty_lists(patch_httpx_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"status": "OK", "result": {"formatted_address": "A"}},
        )

    patch_httpx_client(handler)
    svc = GooglePlacesService(api_key="K")
    details = await svc.get_place_details("p8")
    assert details is not None
    assert details.address == "A"
    assert details.image_urls == []
    # No reviews in response → empty list (not None — None is reserved
    # for "we didn't ask" via include_reviews=False or the use-case
    # blacklist).
    assert details.reviews == []

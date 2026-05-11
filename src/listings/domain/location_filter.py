"""`LocationFilter` — request-side value object for the search read path.

Carries the user's selected location level(s) from the FE selector
into the `SearchListings` use case. At least one level must be set;
the at-least-one invariant is the whole point of the type (the
search route's 422 guard exists to make sure we never even construct
this without a level set, but `__post_init__` is the last-line
defense).

Spec `2026-05-listing-semantic-search-read-path` §"Components to
build" #4.
"""

from __future__ import annotations

from dataclasses import dataclass

from listings.domain.exceptions import EmptyLocationFilterError


@dataclass(frozen=True)
class LocationFilter:
    parish: str | None = None
    municipality: str | None = None
    district: str | None = None

    def __post_init__(self) -> None:
        if not (self.parish or self.municipality or self.district):
            raise EmptyLocationFilterError()

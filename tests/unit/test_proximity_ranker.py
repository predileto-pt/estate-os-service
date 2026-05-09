"""Unit tests for the category-agnostic proximity ranker.

The ranker takes a `known_brands: list[str] | None` parameter directly —
it doesn't know which enum family the value came from. The lookup
happens at the call site via `KNOWN_BRANDS_BY_CATEGORY[category.value]`.
"""

from properties.domain.models.nearby_place import NearbyPlace
from properties.domain.services.proximity_ranker import (
    KNOWN_BRANDS_BY_CATEGORY,
    rank_places,
    rank_top_places,
)

# Helper aliases so the test bodies read naturally.
BANK_BRANDS = KNOWN_BRANDS_BY_CATEGORY["bank"]
GROCERY_BRANDS = KNOWN_BRANDS_BY_CATEGORY["grocery"]


def _place(name: str, distance: float) -> NearbyPlace:
    return NearbyPlace(
        name=name,
        distance_meters=distance,
        latitude=38.72,
        longitude=-9.14,
    )


class TestRankPlaces:
    def test_known_bank_closer_wins(self):
        places = [_place("Millennium BCP", 300), _place("ATM Local", 400)]
        best = rank_places(places, known_brands=BANK_BRANDS)
        assert best.name == "Millennium BCP"

    def test_known_bank_farther_loses_to_very_close_unknown(self):
        # At 100m vs 500m, the 1.5x weight isn't enough to overcome distance
        places = [_place("ATM Local", 100), _place("Millennium BCP", 500)]
        best = rank_places(places, known_brands=BANK_BRANDS)
        assert best.name == "ATM Local"

    def test_known_bank_farther_beats_unknown_at_moderate_distance(self):
        # BPI at 400m vs unknown at 300m — brand boost wins
        places = [_place("ATM Local", 300), _place("BPI", 400)]
        best = rank_places(places, known_brands=BANK_BRANDS)
        assert best.name == "BPI"

    def test_known_grocery_beats_unknown(self):
        places = [_place("Mini Preço", 400), _place("Continente Bom Dia", 500)]
        best = rank_places(places, known_brands=GROCERY_BRANDS)
        assert best.name == "Continente Bom Dia"

    def test_no_brands_uses_nearest(self):
        # Categories without a known-brand list (hospital, school, gym, ...)
        # fall back to nearest-by-distance.
        places = [_place("Hospital A", 300), _place("Hospital B", 200)]
        best = rank_places(places, known_brands=None)
        assert best.name == "Hospital B"

    def test_empty_brands_list_uses_nearest(self):
        places = [_place("Hospital A", 300), _place("Hospital B", 200)]
        best = rank_places(places, known_brands=[])
        assert best.name == "Hospital B"

    def test_case_insensitive_matching(self):
        places = [_place("millennium bcp", 400), _place("ATM", 350)]
        best = rank_places(places, known_brands=BANK_BRANDS)
        assert best.name == "millennium bcp"

    def test_partial_match(self):
        places = [_place("Pingo Doce Express", 500), _place("Mercearia Local", 400)]
        best = rank_places(places, known_brands=GROCERY_BRANDS)
        assert best.name == "Pingo Doce Express"

    def test_caixa_geral_matches(self):
        places = [_place("Caixa Geral de Depósitos", 450), _place("Unknown Bank", 350)]
        best = rank_places(places, known_brands=BANK_BRANDS)
        assert best.name == "Caixa Geral de Depósitos"

    def test_novo_banco_matches(self):
        places = [_place("Novo Banco Ponte de Lima", 400), _place("ATM", 300)]
        best = rank_places(places, known_brands=BANK_BRANDS)
        assert best.name == "Novo Banco Ponte de Lima"

    def test_single_place_returns_it(self):
        places = [_place("Only Option", 1000)]
        best = rank_places(places, known_brands=BANK_BRANDS)
        assert best.name == "Only Option"

    def test_two_known_brands_nearest_wins(self):
        places = [_place("Santander", 300), _place("BPI", 500)]
        best = rank_places(places, known_brands=BANK_BRANDS)
        assert best.name == "Santander"


class TestRankTopPlaces:
    def test_returns_top_5_by_score(self):
        places = [
            _place("ATM 1", 100),
            _place("ATM 2", 200),
            _place("BPI", 300),
            _place("ATM 3", 400),
            _place("Millennium BCP", 500),
            _place("ATM 4", 600),
            _place("Santander", 700),
        ]
        top = rank_top_places(places, known_brands=BANK_BRANDS, limit=5)
        assert len(top) == 5
        # ATM 1 at 100m scores highest (1.0/101 > 1.5/301 for BPI)
        assert top[0].name == "ATM 1"
        # BPI at 300m should rank above ATM 3 at 400m (brand boost)
        top_names = [p.name for p in top]
        assert top_names.index("BPI") < top_names.index("ATM 3")

    def test_returns_all_when_fewer_than_limit(self):
        places = [_place("BPI", 300), _place("ATM", 500)]
        top = rank_top_places(places, known_brands=BANK_BRANDS, limit=5)
        assert len(top) == 2

    def test_no_brands_sorted_by_distance(self):
        places = [
            _place("Hospital C", 500),
            _place("Hospital A", 100),
            _place("Hospital B", 300),
        ]
        top = rank_top_places(places, known_brands=None, limit=5)
        assert [p.name for p in top] == ["Hospital A", "Hospital B", "Hospital C"]

    def test_known_brands_rank_higher(self):
        places = [
            _place("Mini Preço", 300),
            _place("Lidl", 350),
            _place("Continente", 400),
        ]
        top = rank_top_places(places, known_brands=GROCERY_BRANDS, limit=3)
        # Lidl at 350m with brand boost should beat Mini Preço at 300m
        top_names = [p.name for p in top]
        assert top_names[0] == "Lidl"
        assert "Continente" in top_names

    def test_limit_none_returns_every_place_ranked(self):
        """`limit=None` is the municipality-wide knob — every match
        survives ranking, ordered as the policy expects."""
        places = [_place(f"P{i}", float(i * 10)) for i in range(25)]
        top = rank_top_places(places, known_brands=None, limit=None)
        assert len(top) == 25
        assert [p.name for p in top] == [f"P{i}" for i in range(25)]


class TestCategoryAgnosticism:
    """The ranker doesn't import any enum — it operates on plain string
    keys. `KNOWN_BRANDS_BY_CATEGORY` lookups go through `enum.value`,
    so the ranker stays usable for any future enum family that uses
    the same canonical category strings ("bank", "grocery", …).
    """

    def test_brands_lookup_works_via_poi_category_value(self):
        from properties.domain.models.property_poi import PoiCategory

        bank_brands = KNOWN_BRANDS_BY_CATEGORY.get(PoiCategory.BANK.value)
        assert bank_brands is not None
        assert "Millennium" in bank_brands

        grocery_brands = KNOWN_BRANDS_BY_CATEGORY.get(PoiCategory.GROCERY.value)
        assert grocery_brands is not None
        assert "Continente" in grocery_brands

    def test_unknown_category_returns_none(self):
        assert KNOWN_BRANDS_BY_CATEGORY.get("not_a_real_category") is None

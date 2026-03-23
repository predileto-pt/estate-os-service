from property_management.domain.models.property_amenity import (
    AmenityCategory,
    NearbyPlace,
)
from property_management.domain.services.amenity_ranker import rank_places, rank_top_places


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
        best = rank_places(places, AmenityCategory.BANK)
        assert best.name == "Millennium BCP"

    def test_known_bank_farther_loses_to_very_close_unknown(self):
        # At 100m vs 500m, the 1.5x weight isn't enough to overcome distance
        places = [_place("ATM Local", 100), _place("Millennium BCP", 500)]
        best = rank_places(places, AmenityCategory.BANK)
        assert best.name == "ATM Local"

    def test_known_bank_farther_beats_unknown_at_moderate_distance(self):
        # BPI at 400m vs unknown at 300m — brand boost wins
        places = [_place("ATM Local", 300), _place("BPI", 400)]
        best = rank_places(places, AmenityCategory.BANK)
        assert best.name == "BPI"

    def test_known_grocery_beats_unknown(self):
        places = [_place("Mini Preço", 400), _place("Continente Bom Dia", 500)]
        best = rank_places(places, AmenityCategory.GROCERY)
        assert best.name == "Continente Bom Dia"

    def test_non_weighted_category_uses_nearest(self):
        places = [_place("Hospital A", 300), _place("Hospital B", 200)]
        best = rank_places(places, AmenityCategory.HOSPITAL)
        assert best.name == "Hospital B"

    def test_case_insensitive_matching(self):
        places = [_place("millennium bcp", 400), _place("ATM", 350)]
        best = rank_places(places, AmenityCategory.BANK)
        assert best.name == "millennium bcp"

    def test_partial_match(self):
        places = [_place("Pingo Doce Express", 500), _place("Mercearia Local", 400)]
        best = rank_places(places, AmenityCategory.GROCERY)
        assert best.name == "Pingo Doce Express"

    def test_caixa_geral_matches(self):
        places = [_place("Caixa Geral de Depósitos", 450), _place("Unknown Bank", 350)]
        best = rank_places(places, AmenityCategory.BANK)
        assert best.name == "Caixa Geral de Depósitos"

    def test_novo_banco_matches(self):
        places = [_place("Novo Banco Ponte de Lima", 400), _place("ATM", 300)]
        best = rank_places(places, AmenityCategory.BANK)
        assert best.name == "Novo Banco Ponte de Lima"

    def test_single_place_returns_it(self):
        places = [_place("Only Option", 1000)]
        best = rank_places(places, AmenityCategory.BANK)
        assert best.name == "Only Option"

    def test_two_known_brands_nearest_wins(self):
        places = [_place("Santander", 300), _place("BPI", 500)]
        best = rank_places(places, AmenityCategory.BANK)
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
        top = rank_top_places(places, AmenityCategory.BANK, limit=5)
        assert len(top) == 5
        # ATM 1 at 100m scores highest (1.0/101 > 1.5/301 for BPI)
        assert top[0].name == "ATM 1"
        # BPI at 300m should rank above ATM 3 at 400m (brand boost)
        top_names = [p.name for p in top]
        assert top_names.index("BPI") < top_names.index("ATM 3")

    def test_returns_all_when_fewer_than_limit(self):
        places = [_place("BPI", 300), _place("ATM", 500)]
        top = rank_top_places(places, AmenityCategory.BANK, limit=5)
        assert len(top) == 2

    def test_non_weighted_category_sorted_by_distance(self):
        places = [
            _place("Hospital C", 500),
            _place("Hospital A", 100),
            _place("Hospital B", 300),
        ]
        top = rank_top_places(places, AmenityCategory.HOSPITAL, limit=5)
        assert [p.name for p in top] == ["Hospital A", "Hospital B", "Hospital C"]

    def test_known_brands_rank_higher(self):
        places = [
            _place("Mini Preço", 300),
            _place("Lidl", 350),
            _place("Continente", 400),
        ]
        top = rank_top_places(places, AmenityCategory.GROCERY, limit=3)
        # Lidl at 350m with brand boost should beat Mini Preço at 300m
        top_names = [p.name for p in top]
        assert top_names[0] == "Lidl"
        assert "Continente" in top_names

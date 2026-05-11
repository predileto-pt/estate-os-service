"""ListLocations use-case unit tests.

After the 2026-05-11 amendment the use case reads from a bundled
JSON catalog (`src/listings/static_data/locations.json`), not from
the property_listings projection. Tests:

- The default catalog loads cleanly and exposes Portugal.
- The shape is country → district → municipality → parish.
- An empty injected catalog returns `LocationTree(countries=[])`.
- Custom catalogs can be injected via `catalog_path`.

Spec: `2026-05-listing-semantic-search-read-path` §"GET
/api/v1/listings/locations".
"""

from __future__ import annotations

import json
from pathlib import Path

from listings.application.use_cases.list_locations import ListLocations


class TestDefaultCatalog:
    async def test_loads_portugal(self):
        uc = ListLocations()
        tree = await uc.execute()
        # Exactly one country (Portugal) in v1.
        assert len(tree.countries) == 1
        pt = tree.countries[0]
        assert pt.code == "PT"
        assert pt.name == "Portugal"

    async def test_all_twenty_pt_top_level_units(self):
        uc = ListLocations()
        tree = await uc.execute()
        pt = tree.countries[0]
        # 18 mainland districts + Madeira + Açores = 20.
        assert len(pt.districts) == 20
        names = {d.name for d in pt.districts}
        assert "Lisboa" in names
        assert "Porto" in names
        assert "Madeira" in names
        assert "Açores" in names

    async def test_lisboa_has_full_parish_list(self):
        """Lisboa city's 24 parishes (post-2012 reform) are populated
        in full — that's the core promise of the static catalog."""
        uc = ListLocations()
        tree = await uc.execute()
        pt = tree.countries[0]
        lisboa_district = next(d for d in pt.districts if d.name == "Lisboa")
        lisboa_city = next(m for m in lisboa_district.municipalities if m.name == "Lisboa")
        assert len(lisboa_city.parishes) == 24
        assert "Santa Maria Maior" in lisboa_city.parishes
        assert "Belém" in lisboa_city.parishes


class TestCustomCatalog:
    async def test_injected_catalog(self, tmp_path: Path):
        custom = {
            "countries": [
                {
                    "code": "ES",
                    "name": "España",
                    "districts": [
                        {
                            "name": "Madrid",
                            "municipalities": [
                                {"name": "Madrid", "parishes": ["Centro", "Salamanca"]},
                            ],
                        }
                    ],
                }
            ]
        }
        path = tmp_path / "es.json"
        path.write_text(json.dumps(custom), encoding="utf-8")
        uc = ListLocations(catalog_path=path)
        tree = await uc.execute()
        assert len(tree.countries) == 1
        assert tree.countries[0].code == "ES"
        assert tree.countries[0].districts[0].municipalities[0].parishes == ["Centro", "Salamanca"]

    async def test_empty_catalog_returns_empty_tree(self, tmp_path: Path):
        path = tmp_path / "empty.json"
        path.write_text(json.dumps({"countries": []}), encoding="utf-8")
        uc = ListLocations(catalog_path=path)
        tree = await uc.execute()
        assert tree.countries == []

    async def test_municipality_with_empty_parishes(self, tmp_path: Path):
        catalog = {
            "countries": [
                {
                    "code": "PT",
                    "name": "Portugal",
                    "districts": [
                        {
                            "name": "Bragança",
                            "municipalities": [{"name": "Bragança", "parishes": []}],
                        }
                    ],
                }
            ]
        }
        path = tmp_path / "sparse.json"
        path.write_text(json.dumps(catalog), encoding="utf-8")
        uc = ListLocations(catalog_path=path)
        tree = await uc.execute()
        assert tree.countries[0].districts[0].municipalities[0].parishes == []

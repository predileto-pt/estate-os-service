import pytest

from billing.application.use_cases.price_catalog import PriceCatalog
from billing.domain.exceptions import UnknownStripePriceError
from billing.domain.models.subscription import SubscriptionPlan


@pytest.fixture
def catalog() -> PriceCatalog:
    return PriceCatalog(
        pro_monthly="price_pm",
        pro_yearly="price_py",
        enterprise_monthly="price_em",
        enterprise_yearly="price_ey",
    )


class TestPriceIdFor:
    def test_pro_monthly(self, catalog):
        assert catalog.price_id_for(plan=SubscriptionPlan.PRO, cadence="monthly") == "price_pm"

    def test_pro_yearly(self, catalog):
        assert catalog.price_id_for(plan=SubscriptionPlan.PRO, cadence="yearly") == "price_py"

    def test_enterprise_monthly(self, catalog):
        assert (
            catalog.price_id_for(plan=SubscriptionPlan.ENTERPRISE, cadence="monthly") == "price_em"
        )

    def test_enterprise_yearly(self, catalog):
        assert (
            catalog.price_id_for(plan=SubscriptionPlan.ENTERPRISE, cadence="yearly") == "price_ey"
        )

    def test_freemium_rejected(self, catalog):
        with pytest.raises(UnknownStripePriceError):
            catalog.price_id_for(plan=SubscriptionPlan.FREEMIUM, cadence="monthly")


class TestPlanFor:
    def test_pro_price_maps_to_pro(self, catalog):
        assert catalog.plan_for("price_pm") == SubscriptionPlan.PRO
        assert catalog.plan_for("price_py") == SubscriptionPlan.PRO

    def test_enterprise_price_maps_to_enterprise(self, catalog):
        assert catalog.plan_for("price_em") == SubscriptionPlan.ENTERPRISE
        assert catalog.plan_for("price_ey") == SubscriptionPlan.ENTERPRISE

    def test_unknown_price_raises(self, catalog):
        with pytest.raises(UnknownStripePriceError):
            catalog.plan_for("price_other")

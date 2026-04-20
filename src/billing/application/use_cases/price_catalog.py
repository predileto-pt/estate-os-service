"""Maps the (plan, cadence) pair to a configured Stripe price id and
vice-versa. Configured from `Settings` at container build time.
"""

from dataclasses import dataclass
from typing import Literal

from billing.domain.exceptions import UnknownStripePriceError
from billing.domain.models.subscription import SubscriptionPlan

Cadence = Literal["monthly", "yearly"]


@dataclass(frozen=True)
class PriceCatalog:
    pro_monthly: str
    pro_yearly: str
    enterprise_monthly: str
    enterprise_yearly: str

    def price_id_for(self, *, plan: SubscriptionPlan, cadence: Cadence) -> str:
        match (plan, cadence):
            case (SubscriptionPlan.PRO, "monthly"):
                return self.pro_monthly
            case (SubscriptionPlan.PRO, "yearly"):
                return self.pro_yearly
            case (SubscriptionPlan.ENTERPRISE, "monthly"):
                return self.enterprise_monthly
            case (SubscriptionPlan.ENTERPRISE, "yearly"):
                return self.enterprise_yearly
            case _:
                raise UnknownStripePriceError(f"{plan.value}/{cadence}")

    def plan_for(self, price_id: str) -> SubscriptionPlan:
        if price_id in (self.pro_monthly, self.pro_yearly):
            return SubscriptionPlan.PRO
        if price_id in (self.enterprise_monthly, self.enterprise_yearly):
            return SubscriptionPlan.ENTERPRISE
        raise UnknownStripePriceError(price_id)

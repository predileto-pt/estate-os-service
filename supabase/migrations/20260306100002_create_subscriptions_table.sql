CREATE TYPE subscription_plan AS ENUM ('freemium', 'pro', 'enterprise');
CREATE TYPE subscription_type AS ENUM ('stripe', 'manual', 'deposit');
CREATE TYPE subscription_status AS ENUM ('active', 'cancelled', 'past_due', 'trialing', 'inactive');

CREATE TABLE subscriptions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id              UUID NOT NULL REFERENCES companies(id),
    plan                    subscription_plan NOT NULL DEFAULT 'freemium',
    type                    subscription_type NOT NULL,
    status                  subscription_status NOT NULL DEFAULT 'active',
    stripe_subscription_id  TEXT,
    stripe_price_id         TEXT,
    current_period_start    TIMESTAMPTZ,
    current_period_end      TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role can manage subscriptions"
  ON subscriptions FOR ALL
  USING (auth.role() = 'service_role');

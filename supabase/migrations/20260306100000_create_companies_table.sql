CREATE TABLE companies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    tax_id_number   TEXT NOT NULL,
    address_street  TEXT,
    address_parish  TEXT,
    address_municipality TEXT,
    address_district TEXT,
    address_postal_code TEXT,
    address_country TEXT NOT NULL DEFAULT 'PT',
    stripe_customer_id TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE companies ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role can manage companies"
  ON companies FOR ALL
  USING (auth.role() = 'service_role');

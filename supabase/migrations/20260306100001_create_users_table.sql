CREATE TABLE users (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    supabase_user_id    TEXT NOT NULL UNIQUE,
    email               TEXT NOT NULL UNIQUE,
    name                TEXT NOT NULL,
    phone_country_code  TEXT,
    phone_number        TEXT,
    company_id          UUID NOT NULL REFERENCES companies(id),
    google_metadata     JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE users ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own record"
  ON users FOR SELECT
  USING (supabase_user_id = auth.uid()::text);

CREATE POLICY "Users can update own record"
  ON users FOR UPDATE
  USING (supabase_user_id = auth.uid()::text);

CREATE POLICY "Service role can manage users"
  ON users FOR ALL
  USING (auth.role() = 'service_role');

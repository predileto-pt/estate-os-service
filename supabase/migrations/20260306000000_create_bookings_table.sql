create type agendamento_status as enum ('pending', 'approved', 'rejected');

create table agendamentos (
  id                  uuid primary key default gen_random_uuid(),
  property_id         text not null,
  property_title      text not null,
  visitor_name        text not null,
  visitor_email       text not null,
  visitor_phone       text,
  has_id_document     boolean not null default false,
  has_proof_of_income boolean not null default false,
  message             text,
  status              agendamento_status not null default 'pending',
  agency_id           uuid not null references auth.users(id),
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  resolved_at         timestamptz
);

-- RLS: agencies can only see their own visit requests
alter table agendamentos enable row level security;

create policy "Users can view own visit requests"
  on agendamentos for select
  using (auth.uid() = agency_id);

create policy "Users can update own visit requests"
  on agendamentos for update
  using (auth.uid() = agency_id);

create policy "Anyone can insert visit requests"
  on agendamentos for insert
  with check (true);

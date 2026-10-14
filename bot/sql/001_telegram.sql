-- Schéma isolé : aucune modification des tables métier app.*.
CREATE SCHEMA IF NOT EXISTS telegram;
CREATE TABLE IF NOT EXISTS telegram.prospects (
    telegram_user_id bigint PRIMARY KEY,
    track text CHECK (track IN ('etudes','ausbildung','emploi','volontariat')),
    first_name text,
    contact_detail text,
    project_summary text,
    handoff_requested boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS telegram.conversation_state (
    telegram_user_id bigint PRIMARY KEY,
    stage text NOT NULL DEFAULT 'idle',
    data_consent boolean NOT NULL DEFAULT false,
    contact_consent boolean NOT NULL DEFAULT false,
    last_update_id bigint,
    rate_window timestamptz NOT NULL DEFAULT now(),
    rate_count integer NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS telegram.consent_events (
    id bigserial PRIMARY KEY,
    telegram_user_id bigint NOT NULL,
    purpose text NOT NULL CHECK (purpose IN ('data','contact')),
    granted boolean NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS telegram.bot_events (
    update_id bigint PRIMARY KEY,
    telegram_user_id bigint NOT NULL,
    kind text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS telegram_prospects_handoff_idx ON telegram.prospects(handoff_requested, updated_at);

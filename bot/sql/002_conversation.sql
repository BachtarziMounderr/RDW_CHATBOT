-- Extension additive pour l'accueil conversationnel. Aucune table app.* modifiée.
ALTER TABLE telegram.prospects ADD COLUMN IF NOT EXISTS profile_json jsonb;
ALTER TABLE telegram.prospects ADD COLUMN IF NOT EXISTS contact_method text;
ALTER TABLE telegram.prospects ADD COLUMN IF NOT EXISTS contact_confirmed boolean NOT NULL DEFAULT false;
ALTER TABLE telegram.prospects ADD COLUMN IF NOT EXISTS consent_at timestamptz;
ALTER TABLE telegram.prospects ADD COLUMN IF NOT EXISTS consent_version text;
ALTER TABLE telegram.prospects ADD COLUMN IF NOT EXISTS open_questions jsonb;
ALTER TABLE telegram.consent_events ADD COLUMN IF NOT EXISTS text_version text;

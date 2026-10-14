-- Orientation commerciale consentie, sans suppression ni modification destructive.
ALTER TABLE telegram.prospects ADD COLUMN IF NOT EXISTS lead_source text NOT NULL DEFAULT 'direct';
ALTER TABLE telegram.prospects ADD COLUMN IF NOT EXISTS funnel_route text NOT NULL DEFAULT 'undetermined';
ALTER TABLE telegram.prospects ADD COLUMN IF NOT EXISTS offer_status text NOT NULL DEFAULT 'exploring';

UPDATE telegram.prospects
SET funnel_route='consultation', offer_status='consultation_requested'
WHERE handoff_requested=true AND funnel_route='undetermined';

-- Extension additive du formulaire Premium et des reçus VIP.
-- Aucune donnée existante n'est supprimée ou remplacée.
ALTER TABLE telegram.prospects
    ADD COLUMN IF NOT EXISTS admin_notified_at timestamptz DEFAULT now();

ALTER TABLE telegram.payment_events
    ADD COLUMN IF NOT EXISTS media_type text,
    ADD COLUMN IF NOT EXISTS telegram_file_id text,
    ADD COLUMN IF NOT EXISTS telegram_file_unique_id text,
    ADD COLUMN IF NOT EXISTS source_chat_id bigint,
    ADD COLUMN IF NOT EXISTS source_message_id bigint,
    ADD COLUMN IF NOT EXISTS notified_at timestamptz,
    ADD COLUMN IF NOT EXISTS reviewed_by bigint,
    ADD COLUMN IF NOT EXISTS reviewed_at timestamptz,
    ADD COLUMN IF NOT EXISTS invite_link text;

CREATE INDEX IF NOT EXISTS payment_events_pending_idx
    ON telegram.payment_events(status, notified_at, id);

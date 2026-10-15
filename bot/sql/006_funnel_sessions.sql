-- État non personnel du tunnel afin de reprendre après une veille ou un redémarrage.
CREATE TABLE IF NOT EXISTS telegram.funnel_sessions (
    telegram_user_id bigint PRIMARY KEY,
    language text,
    stage text NOT NULL DEFAULT 'idle',
    lead_source text NOT NULL DEFAULT 'direct',
    funnel_route text NOT NULL DEFAULT 'undetermined',
    offer_status text NOT NULL DEFAULT 'exploring',
    private_channel_presented boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (language IS NULL OR language IN ('fr', 'ar'))
);

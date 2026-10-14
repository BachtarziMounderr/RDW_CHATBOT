-- Extensions additives du test privé : aucune table ni ligne existante n'est supprimée.
CREATE TABLE IF NOT EXISTS telegram.knowledge_entries (
    id bigserial PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('answer', 'faq', 'video')),
    question text NOT NULL,
    question_key text NOT NULL,
    answer text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    created_by bigint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS knowledge_entries_lookup_idx
    ON telegram.knowledge_entries(kind, question_key, active, id DESC);

CREATE TABLE IF NOT EXISTS telegram.review_questions (
    id bigserial PRIMARY KEY,
    question_key text NOT NULL UNIQUE,
    question text NOT NULL,
    context_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    category text NOT NULL CHECK (category IN ('needs_answer', 'faq_candidate')),
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'answered')),
    occurrences integer NOT NULL DEFAULT 1,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    notified_at timestamptz,
    answer_entry_id bigint REFERENCES telegram.knowledge_entries(id)
);
CREATE INDEX IF NOT EXISTS review_questions_pending_idx
    ON telegram.review_questions(category, status, notified_at, id);

CREATE TABLE IF NOT EXISTS telegram.history_preferences (
    telegram_user_id bigint PRIMARY KEY,
    enabled boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS telegram.conversation_messages (
    id bigserial PRIMARY KEY,
    telegram_user_id bigint NOT NULL,
    update_id bigint NOT NULL,
    role text NOT NULL CHECK (role IN ('user', 'bot')),
    body text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (update_id, role)
);
CREATE INDEX IF NOT EXISTS conversation_messages_user_idx
    ON telegram.conversation_messages(telegram_user_id, id);

-- Aucun paiement n'est marqué vérifié par une image ou par le bot.
CREATE TABLE IF NOT EXISTS telegram.payment_events (
    id bigserial PRIMARY KEY,
    telegram_user_id bigint,
    provider text,
    external_reference text,
    amount_minor bigint,
    currency char(3),
    status text NOT NULL DEFAULT 'unverified'
        CHECK (status IN ('unverified', 'verified', 'rejected', 'refunded')),
    event_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, external_reference)
);
CREATE INDEX IF NOT EXISTS payment_events_user_idx ON telegram.payment_events(telegram_user_id, id);

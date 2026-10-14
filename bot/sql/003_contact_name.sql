-- Migration additive pour la demande de contact par nom, prénom et téléphone.
ALTER TABLE telegram.prospects ADD COLUMN IF NOT EXISTS last_name text;

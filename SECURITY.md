# Sécurité

Ne placez jamais `TELEGRAM_BOT_TOKEN`, `GROQ_API_KEY`, `DATABASE_URL`, `TELEGRAM_WEBHOOK_SECRET` ou le mot de passe du dashboard dans Git, une issue, une capture d'écran ou un journal public.

Les secrets de production doivent être enregistrés dans les variables du service d'hébergement. Le fichier `.env` local est ignoré par Git et par Docker.

Si une clé est publiée par erreur, révoquez-la immédiatement chez le fournisseur concerné, créez-en une nouvelle et remplacez la variable sur l'hébergeur. Supprimer seulement le dernier commit ne retire pas le secret de l'historique Git.

Le service Telegram doit conserver au maximum une réplique active. Le webhook vérifie le secret transmis par Telegram et la base rejette les mises à jour déjà traitées.

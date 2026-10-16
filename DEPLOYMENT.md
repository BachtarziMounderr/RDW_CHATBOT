# Déployer RDW Assistant avec GitHub, Neon et Render

Cette architecture utilise :

- GitHub privé pour le code ;
- Neon Free pour PostgreSQL ;
- Render Free pour exécuter le conteneur, recevoir le webhook Telegram et servir le dashboard ;
- Groq pour les réponses conversationnelles quand son quota gratuit est disponible.

Vercel n'est pas nécessaire. Le parcours est : GitHub → Render, Telegram → webhook Render, puis Render → Neon et Groq.

## État préparé

- Dépôt : `https://github.com/BachtarziMounderr/RDW_CHATBOT`
- Branche : `main`
- Conteneur : `Dockerfile`
- Blueprint Render : `render.yaml`
- Région : Frankfurt
- Plan : Free
- Contrôle de santé : `/health`
- Accès Telegram initial : privé
- Administrateurs : `7907520730` et `1953680558`

Le fichier `render.yaml` contient uniquement les valeurs publiques. Les secrets sont demandés par Render lors de la création du Blueprint et ne sont jamais enregistrés dans Git.

## 1. Préparer Neon

Créez un projet Neon Free dans une région européenne, de préférence Frankfurt. Conservez la branche, la base et le rôle créés par Neon.

Dans **Connect** :

1. copiez la connexion directe pour la restauration ;
2. copiez la connexion pooled, avec `-pooler` dans l'hôte, pour Render ;
3. vérifiez que l'URL contient `sslmode=require`.

Les URL contiennent le mot de passe PostgreSQL. Ne les placez ni dans GitHub, ni dans Telegram.

## 2. Transférer les données locales

Le bot local doit être arrêté pendant la sauvegarde afin d'obtenir une copie cohérente :

```powershell
cd C:\Users\bacht\Desktop\W_Autom\telegram-bot
.\stop-private.ps1
.\backup-data.ps1
Get-ChildItem .\backups\rdw_bot-*.dump | Sort-Object LastWriteTime -Descending | Select-Object -First 1
.\restore-to-neon.ps1 -BackupPath .\backups\rdw_bot-AAAAMMJJ-HHMMSS.dump
```

Le script demande la connexion Neon directe avec une saisie masquée. Il restaure sans `--clean` et sans supprimer les données existantes.

## 3. Créer le service Render

1. Ouvrez `https://dashboard.render.com/`.
2. Connectez GitHub et accordez l'accès au dépôt privé `RDW_CHATBOT`.
3. Choisissez **New > Blueprint**.
4. Sélectionnez `BachtarziMounderr/RDW_CHATBOT`, branche `main`.
5. Render détecte automatiquement `render.yaml`.
6. Vérifiez avant validation : service `rdw-assistant-bot`, région Frankfurt, plan Free, runtime Docker.

Render demandera ces cinq valeurs :

| Variable | Valeur |
|---|---|
| `TELEGRAM_BOT_TOKEN` | token de `@RDW_assistant_bot` |
| `TELEGRAM_WEBHOOK_SECRET` | chaîne aléatoire d'au moins 32 caractères |
| `DATABASE_URL` | connexion Neon pooled avec `sslmode=require` |
| `GROQ_API_KEY` | clé Groq dédiée au bot |
| `DASHBOARD_PASSWORD` | mot de passe aléatoire d'au moins 16 caractères |
| `BARIDIMOB_PAYMENT_DETAILS` | coordonnées BaridiMob exactes fournies par RDW |
| `CCP_PAYMENT_DETAILS` | coordonnées CCP exactes fournies par RDW |
| `VIP_CHANNEL_ID` | identifiant du canal privé, par exemple `-1001234567890` |

`PAYMENT_PROOF_TELEGRAM=0541501832` reste le contact de support. Les deux coordonnées de paiement peuvent rester vides tant que RDW ne les a pas confirmées ; le bot orientera alors le client vers ce contact sans inventer de numéro. Pour l'accès automatique après contrôle, créez le canal VIP, ajoutez `@RDW_assistant_bot` comme administrateur avec le droit d'inviter, puis copiez son identifiant dans `VIP_CHANNEL_ID`.

Générez localement les deux valeurs aléatoires avec :

```powershell
[Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
```

Exécutez la commande deux fois. Render masque les valeurs marquées comme secrets.

## 4. Déployer et vérifier

Après validation du Blueprint, Render construit le Dockerfile. L'application détecte automatiquement `RENDER_EXTERNAL_URL`, initialise les tables de manière additive et enregistre :

```text
https://DOMAINE.onrender.com/telegram/webhook
```

comme webhook Telegram.

Vérifications obligatoires :

1. le déploiement est **Live** ;
2. `https://DOMAINE.onrender.com/health` répond `{"status":"ok"}` ;
3. la racine ouvre le dashboard protégé par `rdw-admin` et le mot de passe choisi ;
4. votre compte Telegram répond à `/start` et à une question naturelle ;
5. le propriétaire `1953680558` répond à `/start`, `/id` et `/admin` ;
6. les logs ne contiennent aucun token, clé, numéro de téléphone ni texte de conversation.

Le bot n'est opérationnel dans le cloud qu'après un échange Telegram réel réussi.

## 5. Arrêter l'instance locale

Après le test cloud réussi :

```powershell
cd C:\Users\bacht\Desktop\W_Autom\telegram-bot
.\stop-assistant.ps1
```

Le polling local et le webhook cloud ne doivent pas utiliser simultanément le même token.

## 6. Ouvrir aux clients

Après validation du propriétaire, changez sur Render :

```dotenv
TELEGRAM_ACCESS_MODE=public
```

Conservez :

```dotenv
TELEGRAM_ALLOWED_USER_IDS=7907520730,1953680558
RDW_ADMIN_USER_IDS=7907520730,1953680558
```

Puis redéployez. Le lien reste `https://t.me/RDW_assistant_bot`.

## Limites du plan gratuit

Render met un Web Service Free en veille après 15 minutes sans requête entrante. Le premier message suivant déclenche le webhook et réveille le service ; le redémarrage prend généralement environ une minute. Les messages suivants sont rapides tant que le service reste actif.

Render fournit 750 heures gratuites par espace et par mois. Le système de fichiers est éphémère ; toutes les données persistantes doivent rester dans Neon.

## Diagnostic

- `/health` renvoie `503` : consulter les logs Render et vérifier Telegram, Neon et les cinq secrets.
- Telegram ne répond pas : vérifier que le service est Live et que le webhook pointe vers le domaine Render.
- Dashboard `401` : utiliser `rdw-admin` et `DASHBOARD_PASSWORD`.
- Groq échoue : le bot doit utiliser le fallback RAG ; vérifier le quota sans afficher la clé.
- Neon refuse la connexion : recopier l'URL pooled complète avec `sslmode=require`.

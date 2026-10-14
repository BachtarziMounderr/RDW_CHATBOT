# Déployer RDW Assistant avec GitHub, Neon et Koyeb

Cette architecture utilise :

- un dépôt GitHub privé pour le code ;
- Neon Free pour PostgreSQL ;
- un Web Service Koyeb Free qui reçoit les messages par webhook Telegram ;
- Groq pour la rédaction lorsque son quota gratuit est disponible.

Le polling reste disponible pour les essais locaux. Sur Koyeb, le webhook permet à Telegram de réveiller le service lorsqu'un message arrive.

## 1. Créer le dépôt GitHub privé

Sur GitHub, créez un dépôt **Private** vide nommé par exemple `rdw-assistant-bot`. N'ajoutez pas de README, de licence ou de `.gitignore` depuis GitHub.

Dans PowerShell :

```powershell
cd C:\Users\bacht\Desktop\W_Autom\telegram-bot
git init
git add .
git status
git commit -m "Deploy RDW assistant on Neon and Koyeb"
git branch -M main
git remote add origin https://github.com/VOTRE_COMPTE/rdw-assistant-bot.git
git push -u origin main
```

Avant le commit, `git status` ne doit jamais afficher `.env`, `.runtime`, `backups`, `.venv` ni un fichier contenant une clé.

## 2. Créer PostgreSQL sur Neon

1. Ouvrez [Neon](https://console.neon.tech/) et créez un projet Free nommé `rdw-assistant-bot`.
2. Choisissez une région européenne proche de Koyeb Frankfurt, de préférence AWS Frankfurt si elle est proposée.
3. Conservez la branche `main`, la base et le rôle créés par Neon.
4. Ouvrez **Connect**.
5. Copiez d'abord la chaîne **directe**, avec `Pooled connection` désactivé. Elle sert uniquement à restaurer les données.
6. Copiez ensuite la chaîne **pooled**, reconnaissable à `-pooler` dans l'hôte. Elle deviendra le secret `DATABASE_URL` de Koyeb.

Les deux chaînes contiennent le mot de passe de la base. Ne les placez ni dans GitHub, ni dans un message Telegram.

## 3. Copier les données locales existantes vers Neon

Cette étape conserve les fiches consenties et l'historique déjà présent. La restauration s'effectue dans une seule transaction, sans `--clean` et sans suppression.

```powershell
cd C:\Users\bacht\Desktop\W_Autom\telegram-bot
.\stop-private.ps1
.\backup-data.ps1
Get-ChildItem .\backups\rdw_bot-*.dump | Sort-Object LastWriteTime -Descending | Select-Object -First 1
.\restore-to-neon.ps1 -BackupPath .\backups\rdw_bot-AAAAMMJJ-HHMMSS.dump
```

Le dernier script demande la chaîne Neon directe avec une saisie masquée. Si le schéma `telegram` existe déjà, la restauration échoue et la transaction est annulée au lieu d'écraser les données.

Si vous choisissez une base Neon vide sans reprendre les fiches locales, ignorez seulement cette étape : le conteneur créera le schéma de manière additive au premier démarrage.

## 4. Créer les secrets Koyeb

Dans le panneau Koyeb, ouvrez **Secrets** et créez :

| Secret Koyeb | Valeur |
|---|---|
| `RDW_TELEGRAM_TOKEN` | token de `@RDW_assistant_bot` fourni par BotFather |
| `RDW_GROQ_KEY` | clé Groq dédiée au bot |
| `RDW_DATABASE_URL` | chaîne Neon **pooled** avec `sslmode=require` |
| `RDW_WEBHOOK_SECRET` | chaîne aléatoire d'au moins 32 caractères (`A-Z`, `a-z`, chiffres, `_`, `-`) |
| `RDW_DASHBOARD_PASSWORD` | mot de passe aléatoire d'au moins 16 caractères |

Pour générer localement les deux valeurs aléatoires dans PowerShell :

```powershell
[Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
```

Exécutez la commande deux fois et conservez chaque résultat dans le secret correspondant. Ces valeurs ne doivent pas être ajoutées au dépôt.

## 5. Créer le Web Service Koyeb

1. Ouvrez [Koyeb](https://app.koyeb.com/) et cliquez sur **Create Web Service**.
2. Choisissez **GitHub**, installez l'application Koyeb et autorisez uniquement le dépôt privé du bot.
3. Sélectionnez le dépôt et la branche `main`.
4. Choisissez le builder **Dockerfile**. Le fichier est à la racine ; ne remplacez ni son `CMD`, ni son `ENTRYPOINT`.
5. Type : **Web Service**.
6. Région : **Frankfurt**.
7. Instance : **Free** (512 MB). Cette instance passe automatiquement en veille après une heure sans trafic.
8. Exposez le port `8080` en HTTP et routez `/` vers ce port. Koyeb fournit aussi automatiquement `PORT`.
9. Conservez une seule instance. L'offre Free ne doit pas être remplacée par une instance payante.

## 6. Ajouter les variables Koyeb

Dans **Environment variables and files > Bulk Edit**, ajoutez les valeurs suivantes. Les cinq références `secret.*` doivent pointer vers les secrets créés à l'étape précédente.

```dotenv
TELEGRAM_BOT_TOKEN={{ secret.RDW_TELEGRAM_TOKEN }}
BOT_MODE=assistant
TELEGRAM_TRANSPORT=webhook
WEBHOOK_PUBLIC_URL=https://{{ KOYEB_PUBLIC_DOMAIN }}
TELEGRAM_WEBHOOK_PATH=/telegram/webhook
TELEGRAM_WEBHOOK_SECRET={{ secret.RDW_WEBHOOK_SECRET }}

TELEGRAM_ACCESS_MODE=private
TELEGRAM_ALLOWED_USER_IDS=7907520730,1953680558
RDW_ADMIN_USER_IDS=7907520730,1953680558
DATABASE_URL={{ secret.RDW_DATABASE_URL }}

AI_ENABLED=true
AI_PROVIDER=groq
GROQ_API_KEY={{ secret.RDW_GROQ_KEY }}
GROQ_MODEL=qwen/qwen3.8-27b

DASHBOARD_ENABLED=true
DASHBOARD_HOST=0.0.0.0
DASHBOARD_USERNAME=rdw-admin
DASHBOARD_PASSWORD={{ secret.RDW_DASHBOARD_PASSWORD }}

CONSULTATION_PRICE_DZD=2000
PRIVATE_CHANNEL_PRICE_DZD=500
DEBUG_SOURCE_LABELS=false
AI_MAX_CALLS_PER_USER_DAY=400
AI_MAX_CALLS_PER_DAY=800
AI_MAX_INPUT_CHARS=7000
AI_MAX_OUTPUT_TOKENS=240
AI_TIMEOUT_SECONDS=25
AI_MAX_RETRIES=1
AI_QUOTA_COOLDOWN_SECONDS=120
```

`1953680558` est le compte du propriétaire. `7907520730` est le compte utilisé pour les essais actuels. Les deux peuvent utiliser les commandes administrateur. Les identifiants restent des variables d'hébergement et ne sont pas ajoutés au code.

## 7. Configurer le contrôle de santé et déployer

Dans **Health checks** :

- protocole : `HTTP` ;
- méthode : `GET` ;
- chemin : `/health` ;
- délai initial : `60` secondes ;
- timeout : `5` secondes ;
- restart limit : `3`.

Cliquez sur **Deploy**. Le conteneur applique les migrations additives, vérifie que le token appartient à `@RDW_assistant_bot`, enregistre le webhook HTTPS auprès de Telegram et ne rend `/health` positif qu'après confirmation de Telegram.

Dans les logs, la ligne attendue est :

```text
Assistant RDW en démarrage avec webhook Telegram.
```

Les tokens, clés, coordonnées et textes des conversations ne doivent pas apparaître dans les logs.

## 8. Vérifier le déploiement privé

1. Ouvrez `https://DOMAINE-KOYEB/health` : la réponse doit être `{"status":"ok"}`.
2. Ouvrez `https://DOMAINE-KOYEB/` et connectez-vous avec `rdw-admin` et le mot de passe du dashboard.
3. Depuis votre compte Telegram, envoyez `/start`, puis une question naturelle.
4. Depuis le compte du propriétaire `1953680558`, envoyez `/start`, `/id`, puis `/admin`.
5. Laissez ensuite le service sans trafic pendant plus d'une heure et envoyez un nouveau message. La première réponse peut être retardée par le réveil de Koyeb et de Neon ; les suivantes doivent être plus rapides.
6. Vérifiez dans les métriques Koyeb qu'une seule instance est active et dans Neon que les données attendues sont présentes.

Le déploiement n'est considéré comme opérationnel qu'après un échange réel réussi depuis chacun des deux comptes.

## 9. Arrêter définitivement l'instance locale

Une fois le test cloud réussi, arrêtez le bot et PostgreSQL locaux :

```powershell
cd C:\Users\bacht\Desktop\W_Autom\telegram-bot
.\stop-assistant.ps1
```

N'exécutez plus `restart-assistant.ps1` avec le même token tant que le webhook Koyeb est actif. Telegram n'autorise pas le polling `getUpdates` en même temps qu'un webhook.

## 10. Ouvrir le bot aux clients

Après validation du propriétaire, changez seulement cette variable dans Koyeb :

```dotenv
TELEGRAM_ACCESS_MODE=public
```

Conservez les deux identifiants dans `TELEGRAM_ALLOWED_USER_IDS` et `RDW_ADMIN_USER_IDS` pour que vous et le propriétaire gardiez les commandes de gestion. Cliquez sur **Deploy** pour appliquer le changement. Le lien client reste :

[https://t.me/RDW_assistant_bot](https://t.me/RDW_assistant_bot)

Pour refermer l'accès, remettez `TELEGRAM_ACCESS_MODE=private` puis redéployez.

## 11. Mises à jour et sauvegardes

- Chaque push sur `main` déclenche un redéploiement si **Autodeploy** est activé.
- Conservez au moins une sauvegarde chiffrée hors de Koyeb et Neon.
- Surveillez l'espace, les CU-hours et les restaurations disponibles dans Neon.
- Surveillez les métriques, les redémarrages et les erreurs dans Koyeb.
- Le plan Koyeb Free est destiné aux tests et projets personnels, sans garantie de production. Une première réponse après veille prend généralement quelques secondes de plus.

## Diagnostic rapide

- `/health` renvoie `503` : ouvrez les logs Koyeb ; le token, Neon ou l'enregistrement du webhook a échoué.
- Telegram ne répond pas : vérifiez `TELEGRAM_TRANSPORT=webhook`, `WEBHOOK_PUBLIC_URL`, le secret webhook et l'état `Healthy` du déploiement.
- Le dashboard renvoie `401` : utilisez `DASHBOARD_USERNAME` et le secret `RDW_DASHBOARD_PASSWORD`.
- Groq ne répond pas : le bot doit revenir au RAG ; vérifiez le quota et `RDW_GROQ_KEY` sans afficher sa valeur.
- La base refuse la connexion : recopiez la chaîne Neon pooled complète, avec `sslmode=require`.

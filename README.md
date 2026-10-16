# Assistant Telegram RDW

Le mode `assistant` accueille en français ou en arabe, informe à partir du seul [corpus public actif](bot/data/public_corpus.json), puis aide à préciser un projet avant de proposer un rappel facultatif. Le corpus vient du [PDF *Ta route vers l'Allemagne*](bot/assets/Ta-route-vers-l-Allemagne-RDW.pdf), édition 2026 (43 pages, empreinte SHA-256 enregistrée dans le JSON). Chaque passage indique les pages, la section et la version. L'[ancien corpus](bot/data/archive/public_corpus_2026-10-07.json) est archivé hors de la recherche active pour permettre un retour arrière explicite.

Le PDF décrit les **études supérieures, l'Ausbildung et l'emploi**. Il ne décrit pas de prestation RDW pour le volontariat : le bot ne la propose donc pas. Il contient aussi des montants de financement et des formulations de garanties divergents. Le bot ne confirme aucune admissibilité, décision de visa, embauche, admission ou garantie contractuelle. Il présente les tarifs du *guide 2026* comme des indications à confirmer, pas comme un devis actuel. La sélection publique écarte les histoires personnelles, les noms des personnes citées, les contacts de recruteurs et les détails internes. RDW doit valider cette sélection avant une ouverture au public.

## Tunnel Telegram préparé

Le lien à placer dans le canal Telegram gratuit est :

[https://t.me/RDW_assistant_bot?start=canal_gratuit](https://t.me/RDW_assistant_bot?start=canal_gratuit)

Telegram demande toujours à la personne d'appuyer sur **Démarrer** avant qu'un bot puisse lui écrire. Dès cette action, le bot demande le français ou l'arabe, envoie le PDF original, puis affiche `📖 J'ai lu l'Ebook / Continuer`. Le bouton présente l'accompagnement Premium et laisse choisir entre l'agence et une démarche autonome. Une question posée pendant ce parcours reçoit une réponse avant la reprise de l'étape. Le paramètre `canal_gratuit` est enregistré dans la fiche uniquement après le consentement final.

Le routage distingue deux voies après l'Ebook :

- **Premium** : le candidat confirme cette voie, choisit son projet puis remplit dans le bot le formulaire nom, prénom, âge, diplôme, domaine, allemand, anglais, expérience et téléphone. Après consentement, la fiche apparaît dans le dashboard et les administrateurs reçoivent une notification ; aucun paiement de consultation n'est demandé dans le bot ;
- une personne qui cherche des informations sur RDW ou le guide : réponses fondées sur le corpus actif et commande `/guide` pour voir les sujets disponibles ;
- **Solo** : présentation du canal VIP à `1 000 DA`, paiement unique pour un accès à vie, avec lives, ressources, pratique de l'allemand, entraide et possibilité de passer ensuite au Premium. La commande `/canal` affiche cette offre.

Le prix VIP est configurable avec `PRIVATE_CHANNEL_PRICE_DZD`. Les coordonnées réelles de paiement doivent être saisies dans `BARIDIMOB_PAYMENT_DETAILS` et `CCP_PAYMENT_DETAILS`, et le nom officiel du titulaire CCP dans `CCP_ACCOUNT_HOLDER_NAME` ; si les coordonnées sont vides, le bot demande au client de les obtenir auprès du support `PAYMENT_PROOF_TELEGRAM` au lieu d'en inventer. Le client envoie ensuite la photo ou le PDF du reçu directement au bot. Le reçu reste `unverified` jusqu'au clic d'un administrateur. Après validation, le bot crée un lien Telegram limité à un membre et l'envoie au client. `VIP_CHANNEL_ID` doit contenir l'identifiant du canal privé et le bot doit y être administrateur avec le droit de créer des invitations.

## Démarrer et arrêter

Le bot reste réservé aux identifiants de `TELEGRAM_ALLOWED_USER_IDS` dans `.env`. Le token Telegram et l'URL PostgreSQL sont déjà configurés localement ; **ne les copiez pas dans un message**. Le démarrage vérifie que le token correspond à `@RDW_assistant_bot`. La base dédiée au bot est dans `.runtime/postgres`, sur `127.0.0.1:55432`, avec authentification par mot de passe. Le PostgreSQL préexistant sur le PC n'est pas modifié. `.env` et `.runtime` sont ignorés par Git.

Pour exécuter le bot sans laisser ce PC allumé, utilisez le [guide GitHub, Neon et Render](DEPLOYMENT.md). Le dépôt inclut un `Dockerfile`, un Blueprint Render, un transport webhook sécurisé, l'initialisation non destructive de PostgreSQL, un contrôle `/health`, une authentification du dashboard et des tests GitHub Actions. Les secrets restent dans Neon et Render.

Depuis PowerShell, dans `C:\Users\bacht\Desktop\W_Autom\telegram-bot` :

```powershell
.\start-assistant.ps1
.\stop-assistant.ps1
.\restart-assistant.ps1
```

Le premier script démarre PostgreSQL si nécessaire, applique des migrations additives et lance le bot en arrière-plan. Le second arrête le bot puis sa base locale. Pour relancer, exécutez de nouveau `start-assistant.ps1`. Si PowerShell bloque les scripts, utilisez `powershell -ExecutionPolicy Bypass -File .\start-assistant.ps1`. Le PC doit rester allumé et connecté à Internet, avec le programme lancé.

Chaque démarrage crée auparavant une sauvegarde PostgreSQL horodatée dans `telegram-bot/backups`. Aucune sauvegarde n'est écrasée automatiquement. Copiez périodiquement ce dossier sur un support protégé hors du PC : une sauvegarde située sur le même disque ne couvre pas une panne matérielle ou un vol.

Le verrou `.runtime/bot.lock` empêche deux instances de ce programme de traiter les messages. `.runtime/ready.json` confirme la connexion à Telegram, le mode et le nombre de comptes autorisés, sans token ni texte. `.runtime/exchanges.json` garde seulement des compteurs ; une connexion réussie ne remplace pas un vrai essai depuis Telegram.

## Dashboard local des demandes

Le mode assistant démarre aussi un dashboard en lecture seule sur [http://127.0.0.1:8765](http://127.0.0.1:8765). Il affiche les fiches dont les coordonnées ont été confirmées et dont le consentement a été enregistré : nom, prénom, téléphone, projet, faits déclarés, questions ouvertes et date de mise à jour. Les filtres séparent études, emploi, Ausbildung et volontariat. La catégorie volontariat reste visible pour d'éventuelles anciennes fiches, même si le corpus actif ne présente pas cette offre.

Le dashboard ne montre pas l'identifiant Telegram et ne recopie pas le texte brut des conversations. Il lit PostgreSQL directement à chaque actualisation. En local, il est lié à `127.0.0.1`. Sur Render, il écoute sur `0.0.0.0` uniquement si `DASHBOARD_USERNAME` et un `DASHBOARD_PASSWORD` d'au moins 16 caractères sont fournis ; Render apporte HTTPS.

Configuration locale :

```dotenv
DASHBOARD_ENABLED=true
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8765
```

Le dashboard suit le cycle du bot : `start-assistant.ps1` le démarre et `stop-assistant.ps1` l'arrête. L'URL active apparaît aussi dans `.runtime/ready.json`.

## Ajouter le propriétaire au test privé

Le propriétaire ouvre [@RDW_assistant_bot](https://t.me/RDW_assistant_bot) depuis **son propre compte Telegram**, appuie sur Démarrer et envoie `/id`. Son identifiant `1953680558` est déjà ajouté au `.env` local comme compte autorisé et administrateur. Il pourra utiliser `/start`, poser une question, décrire un projet et ouvrir `/admin` après le prochain redémarrage local ou le déploiement Render.

Pour lui confier la gestion des contenus, mettez aussi son identifiant dans `RDW_ADMIN_USER_IDS`. Pendant une période de passation, cette variable peut contenir les deux identifiants séparés par une virgule. Les commandes `/admin`, `/attente`, `/repondre`, `/faq_ajouter`, `/contenu` et `/video` sont alors disponibles depuis son compte. Lorsqu'un administrateur pose lui-même une question sans réponse pendant un test, elle reste consultable dans `/attente`, mais l'alerte interne n'est plus envoyée dans sa propre conversation.

## Ouvrir ensuite le bot aux clients

Le propriétaire n'a pas besoin de connecter son compte personnel aux comptes des clients. Une fois les essais terminés, il partage simplement [https://t.me/RDW_assistant_bot](https://t.me/RDW_assistant_bot). Chaque client ouvre une conversation privée distincte avec le bot.

Avant ce partage, modifiez la variable Render :

```dotenv
BOT_MODE=assistant
TELEGRAM_ACCESS_MODE=public
TELEGRAM_ALLOWED_USER_IDS=7907520730,1953680558
RDW_ADMIN_USER_IDS=7907520730,1953680558
```

`TELEGRAM_ALLOWED_USER_IDS` continue alors d'identifier les comptes de gestion ; la restriction des conversations est désactivée par `TELEGRAM_ACCESS_MODE=public`. Redéployez le service Render. Pour refermer immédiatement l'accès, remettez `TELEGRAM_ACCESS_MODE=private` puis redéployez. Le PC personnel peut rester éteint une fois la migration et le test cloud terminés.

## Conversation et données

`/start` présente RDW et demande la voie souhaitée ; `/aide` liste les commandes ; `/source` cite le passage du guide de la dernière réponse ; `/reprendre` poursuit un échange en pause ; `/annuler` le suspend ; `/humain` commence une demande de rappel ; `/mes_donnees` montre la fiche durable ; `/supprimer` l'efface. Le bot répond aux questions pendant la qualification et revient à la question en cours.

Une personne peut aussi dire « Je veux juste me renseigner sur l'agence » ou demander des informations sans point d'interrogation. Le bot répond alors depuis le corpus RDW et reste en mode information tant qu'aucun projet n'est déclaré. Pendant une qualification, une question sur l'agence, le CV, les documents ou l'accompagnement reçoit une réponse avant la reprise de l'étape en cours. Les transitions entre les champs sont rédigées naturellement par le fournisseur IA lorsqu'il est disponible ; Python conserve la validation et une formulation locale de repli.

Le bot reconnaît aussi des formulations courantes en daridja algérienne, en alphabet latin, en Arabizi ou en arabe, par exemple « wach tdirou », « ch7al souma » et « nheb nqra master ». Il répond en français ou en arabe selon le choix fait au démarrage. Lorsqu'elle passe les contrôles locaux, la question non sensible peut être transmise à Groq avec les passages publics du guide afin de comprendre les reformulations. Les coordonnées, identifiants Telegram, documents et étapes de collecte restent locaux. Ce filtrage ne rend pas le texte anonyme.

Avant l'accord final, les données du formulaire Premium restent uniquement en mémoire du processus, au plus deux heures après le dernier message. Neon conserve seulement la langue et l'étape commerciale sans texte libre ni coordonnées afin de reprendre le tunnel après un redémarrage. Le bot confirme le téléphone, présente le [texte d'accord versionné](bot/data/consent_rdw_contact_v5_2026-10-16.txt), puis enregistre le formulaire dans PostgreSQL seulement après « J'accepte ». Un mobile algérien peut être saisi directement au format local, par exemple `0550123456` ; le bot le convertit en `+213550123456` avant confirmation. Les formats internationaux avec `+` ou `00` restent acceptés.

Pour exporter localement les demandes consenties dans un **nouveau** CSV à remettre seulement à l'équipe RDW :

```powershell
New-Item -ItemType Directory -Force .\exports | Out-Null
.\.venv\Scripts\python.exe -m bot.main export-handoffs --output .\exports\demandes-rdw.csv
```

L'export refuse d'écraser un fichier. Le CSV contient des données personnelles ; protégez-le et supprimez les copies devenues inutiles.

## Questions sans réponse, FAQ et contenus

Le compte indiqué dans `RDW_ADMIN_USER_IDS` est l'administrateur de contenu. Il doit aussi être présent dans `TELEGRAM_ALLOWED_USER_IDS`. Lorsqu'une question pertinente n'a pas de réponse vérifiée, le bot l'enregistre avec le parcours, l'étape et uniquement les faits de projet à valeurs contrôlées, puis envoie à l'administrateur :

```text
/repondre N Votre réponse validée
```

La réponse devient une extension locale de la base et sera réutilisée pour la même question. Les questions manifestement hors sujet et les répétitions sont classées dans `faq_candidate` sans nouvelle notification. Après plusieurs tours sans progression, le bot propose `/faq`.

L'interface de gestion reste dans Telegram :

- `/admin` : aide de gestion ;
- `/attente` : questions à traiter ;
- `/repondre N réponse` : publier une réponse validée ;
- `/faq_candidats` : questions absurdes, hors sujet ou répétées ;
- `/faq_ajouter Question | Réponse` : ajouter une FAQ proposée par `/faq` ;
- `/contenu Question | Réponse` : ajouter une réponse documentaire ;
- `/video Titre | https://...` : publier un lien YouTube ou Vimeo dans `/videos` ;
- `/paiements` : afficher les nombres d'événements par statut.
- `/valider_paiement N` : valider manuellement le reçu N et envoyer un lien VIP à usage unique ;
- `/refuser_paiement N` : refuser le reçu N et inviter le client à renvoyer une preuve correcte.

Une vidéo est publiée comme ressource. Elle ne devient une source factuelle du RAG qu'après ajout d'une transcription ou d'une réponse textuelle validée. Les commandes de gestion sont refusées aux autres comptes.

## Stockage, Excel et paiements

PostgreSQL reste la source principale : il gère les mises à jour simultanées, les doublons, les consentements et les relations entre clients, questions, réponses et paiements. Excel est adapté à la consultation et au reporting, mais pas comme base active d'un bot : un fichier ouvert, déplacé ou modifié manuellement peut bloquer les écritures ou créer des doublons. Les fiches consenties sont donc exportables en CSV, directement ouvrable dans Excel, avec la commande `export-handoffs` décrite plus haut.

Les nouvelles tables additives sont :

- `knowledge_entries` pour les réponses, FAQ et vidéos validées ;
- `review_questions` pour les questions à traiter et les candidats FAQ ;
- `history_preferences` et `conversation_messages` pour l'historique volontaire ;
- `payment_events` pour les références Telegram des reçus, leur statut de contrôle, l'administrateur ayant traité le reçu et le lien généré ;
- `funnel_sessions` pour la langue et l'étape non personnelle du parcours.

L'historique brut est désactivé par défaut. La personne peut utiliser `/historique_on` avant la conversation, `/historique_off` pour arrêter les nouvelles écritures et `/supprimer` pour supprimer sa fiche et son historique local. Cela évite de conserver silencieusement des conversations personnelles. Telegram garde ses propres messages selon ses règles.

Aucun prestataire de paiement n'est connecté et le bot ne fait aucune reconnaissance automatique des captures. Il accepte une photo ou un PDF seulement à l'étape VIP, conserve la référence de fichier Telegram et la transmet aux administrateurs. Seul un administrateur autorisé peut passer le reçu à `verified`, après vérification visuelle. La contrainte d'unicité sur `(provider, external_reference)` limite les doublons. La validation déclenche un lien `createChatInviteLink` avec `member_limit=1`.

## Groq en test privé

Le [transport Groq](bot/groq_dialogue.py) utilise le SDK Python officiel `groq` et le modèle `qwen/qwen3.8-27b`. La documentation Groq affiche actuellement pour ce modèle, sur le Free Plan, 30 requêtes par minute, 1 000 par jour, 8 000 jetons par minute et 200 000 par jour. Vérifiez les limites exactes de votre organisation dans la [page Limits de Groq](https://console.groq.com/docs/rate-limits). Le code n'active aucune facturation et refuse tout modèle qui n'est pas dans sa liste locale autorisée. Il ne bascule pas automatiquement vers un autre modèle ou un autre fournisseur.

Groq rédige une courte réponse à partir du [corpus public actif](bot/data/public_corpus.json). Python garde les validations, le parcours, les coordonnées, le consentement et l'enregistrement. L'appel contient la question filtrée, les passages publics pertinents ou un catalogue compact de leurs faits approuvés, certains faits de projet à valeurs contrôlées et une seule orientation active. Aucun historique libre n'est envoyé. Les messages qui semblent contenir des coordonnées, un nom complet, un document, un identifiant ou une tentative de modifier les règles sont exclus de l'appel. Ce filtrage ne rend pas le texte anonyme, notamment vis-à-vis de Groq et de Telegram. Groq peut reformuler les tarifs, limites et conditions lorsque le passage transmis les documente. Ses réponses sont validées localement sur leur structure, leur provenance, leurs nombres, leurs affirmations sensibles et le nombre de questions. Si le quota, le réseau ou la validation échoue, le bot utilise silencieusement la réponse documentaire locale. Hors mode de diagnostic, le client ne voit ni nom de fournisseur, ni code HTTP, ni message de contrôle interne. `.runtime/ai_status_groq.json` conserve localement le dernier type de résultat, le fournisseur, le modèle, la date et, le cas échéant, le code HTTP et l'heure de reprise ; jamais le texte ni l'identifiant. `/source` donne la provenance exacte des passages retenus par Groq.

Une question documentaire reçoit d'abord une réponse ; elle ne déclenche plus automatiquement une qualification ou le choix entre agence et canal privé. Une intention explicite d'avancer seul peut proposer le canal privé, tandis qu'une intention claire de consultation peut commencer le parcours agence. Pour comprendre une relance courte, la session garde uniquement le dernier identifiant documentaire public, par exemple `documents` ou `consultation`, sans envoyer l'historique libre à Groq.

Groq parle au nom de l'agence avec « nous », « nos services » et « notre agence ». Après avoir répondu, il peut poser au maximum une question naturelle correspondant à l'objectif actif : approfondir une information du guide, préparer une consultation avec un conseiller commercial, ou présenter le canal privé seulement si la personne indique vouloir avancer par elle-même. Il ne présente pas ces possibilités sous forme de menu numéroté.

Le bot reconnaît aussi le français algérien et des formulations courantes de daridja écrites en lettres latines, en arabe ou avec les chiffres `3`, `7` et `9`. Le message original filtré est transmis à Groq avec une indication de contexte algérien et la langue choisie ; la réponse est en français ou en arabe. Les signaux locaux servent à reconnaître le sujet ou le projet, puis Groq interprète la phrase complète.

Pendant les essais, `DEBUG_SOURCE_LABELS=true` ajoute `Réponse Groq :` ou `Réponse RAG :` au début du message. Remettez cette variable à `false` avant une diffusion aux prospects.

Pour activer volontairement des appels, dans `telegram-bot/.env`, collez la clé **dédiée** après `GROQ_API_KEY=`, puis utilisez `AI_ENABLED=true`, `AI_PROVIDER=groq` et `GROQ_MODEL=qwen/qwen3.8-27b`. Ne copiez la clé ni dans une commande, ni dans un message. Les plafonds locaux configurés dans [.env.example](.env.example) sont de 400 appels par compte et 800 au total par jour UTC, ce qui garde une marge sous le plafond public de 1 000 requêtes. Chaque retry consomme aussi un compteur. La requête est limitée à 7 000 caractères, la sortie à 240 jetons, le délai à 25 secondes et le retry à un maximum. Après HTTP 429, le bot applique une pause locale. Les compteurs persistent dans `.runtime/ai_usage_groq.json`, sans texte de conversation. Une réponse non conforme provoque un repli local.

Depuis PowerShell, après avoir vérifié le Free Tier et enregistré la clé localement :

```powershell
.\activate-groq.ps1
```

`activate-groq.ps1` active la configuration, fait **un véritable appel Groq** avec une question synthétique sur les filières, sans Telegram ni profil réel, puis redémarre une seule instance du bot si le contrôle réussit. Si la clé, le quota ou la réponse ne conviennent pas, il remet `AI_ENABLED=false` et laisse le bot actuel en mode documentaire. Le test reste limité aux deux identifiants autorisés ; le propriétaire doit envoyer `/id` depuis son propre compte pour être ajouté. Après connexion, vérifiez plusieurs dialogues réels en français depuis Telegram avant de considérer la fluidité validée.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Les tests IA utilisent de faux transports : ils vérifient notamment la rédaction française et arabe, la provenance, le repli, la confidentialité des requêtes, les timeouts, les réponses 429 et le JSON invalide, sans évaluer un modèle réel. Les tests PostgreSQL s'exécutent lorsque `TEST_TELEGRAM_DATABASE_URL` pointe vers une base de test dédiée. Les migrations additives sont dans `bot/sql`.

# Audit de sécurité du socle Mail Pilot (novembre 2026)

Périmètre : `backend/app/`, `frontend/src/`, `Dockerfile`, `docker-compose.yml`, `deploy/`.
Contexte : application mono-utilisateur, exposée sur Internet derrière le domaine de Mathis et un reverse proxy HTTPS ; Claude Code CLI appelé en headless sur du contenu de mail **non fiable**.

## Méthode

- Méthodologie ECC appliquée manuellement (le plugin reste désactivé) : `agents/security-reviewer.md` (OWASP Top 10, motifs à signaler), `skills/security-review/SKILL.md` (secrets, validation, injection, auth, XSS, CSRF, limitation de débit, fuite de données, dépendances), `skills/agent-security-hardening/SKILL.md` (frontières de confiance, sortie de modèle non fiable, sous-processus, secrets), règles `rules/python/*` et `rules/react/security.md`.
- Revue de code ligne à ligne des zones à risque : authentification, sessions, CSRF, limitation des connexions, chiffrement des identifiants, nettoyage HTML et iframe du lecteur, appel de Claude (drapeaux du runner, environnement, prompts, schéma, stockage du jeton), sous-processus, en-têtes HTTP, endpoints sortants (Web Push, Gotify, IMAP), Docker.
- Outils :
  - `pip-audit` (backend) : 0 vulnérabilité dans les dépendances de l'appli ; 12 avis sur `pip 24.0` du venv (outil d'installation, hors exécution). Premier essai en échec TLS (proxy d'entreprise), relancé avec `REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt`.
  - `npm audit --audit-level=high` (front) : code de sortie 0 ; 6 avis (2 faibles, 4 modérés) tous dans la chaîne de build `vite-plugin-pwa` → `workbox-build` → `glob`/`minimatch`/`@rollup/plugin-node-resolve`/`deepmerge`, absente du bundle livré.
  - AgentShield (`npx ecc-agentshield scan -p .`) : note A (99/100), 2 constats MOYEN sur `.claude/settings.local.json` (configuration de l'**environnement de dev** : pas de bloc `permissions`, pas de hook PreToolUse). AgentShield n'analyse que les configurations Claude Code (`.claude/`, MCP, hooks, agents) : la configuration **embarquée** du runner a donc été revue manuellement (section dédiée ci-dessous).
- Vérification à l'exécution : image `mail-pilot:latest` démarrée avec `--cap-drop ALL --security-opt no-new-privileges:true` → `/api/health` 200, `CapEff=0`, `NoNewPrivs=1`, `claude --version` OK.

## Revue de la configuration Claude embarquée (équivalent AgentShield)

`backend/app/claude/runner.py` :

- `--tools ""` (aucun outil), `--strict-mcp-config` sans `--mcp-config` (aucun serveur MCP), `--setting-sources ""` (aucun réglage/hook utilisateur ou projet chargé), `--no-session-persistence`, jamais `--bare` ni `ANTHROPIC_API_KEY` (tests existants).
- Environnement du sous-processus en liste blanche : `PATH`, `HOME` (=`/data/claude-home`), `LANG`, `CLAUDE_CODE_OAUTH_TOKEN` ; aucune autre variable (dont `MP_SECRET_KEY`) n'est transmise.
- `create_subprocess_exec` (pas de shell) ; le prompt passe par stdin, le jeton par l'environnement (jamais en argument).
- Jeton : chiffré Fernet dans `/data/claude-token.enc`, écrit en `0600` par remplacement atomique ; testé avant enregistrement ; jamais renvoyé par l'API.
- Sortie : JSON validé par `jsonschema` (catégorie en énumération, dates au format strict, `additionalProperties: false`), ids inconnus/dupliqués ignorés, `reason`/`summary` tronqués, rendus en texte par React. Toute sortie hors schéma → lot non classé.
- Prompt : contenu encadré par `<mail-non-fiable id="…">`, consigne explicite dans le prompt système ; balises imitées neutralisées (renforcé par C-02).

Impact résiduel d'une injection réussie : une **mauvaise catégorie** (ex. hameçonnage classé « important » → alerte). Aucune action irréversible : le nettoyage `pub`/`spam` est déclenché par l'utilisateur et déplace vers la corbeille (annulable).

## Constats

| ID | Gravité | Fichier:ligne | Description | Décision |
|----|---------|---------------|-------------|----------|
| C-01 | ÉLEVÉ | `backend/app/notify/webpush.py:32-37` | Contournement de la liste blanche anti-SSRF des endpoints Web Push par différentiel de parseurs : `https://evil.com\.fcm.googleapis.com/x` est accepté (`urlsplit` voit l'hôte `…fcm.googleapis.com`) alors que `requests`/`urllib3` contactent `evil.com`. Idem `%2f` dans l'hôte, `\n` dans le chemin. Un POST serveur vers un hôte arbitraire (y compris réseau interne, port 443) devient possible depuis une session. | **Corrigé** : forme stricte de l'URL avant parsing (`re.ASCII` : pas de repli de casse Unicode, hôte `[A-Za-z0-9.-]`, chemin sans espace, contrôle, antislash ni `#`) ; s'applique à l'abonnement et à l'envoi (abonnements déjà en base). Tests `test_subscribe_rejects_unsafe_endpoint` (10 cas ajoutés), `test_send_webpush_refuses_parser_differential_endpoint`, endpoints réels conservés (Windows avec `%`, FCM avec `:`/`~`). |
| C-02 | MOYEN | `backend/app/claude/prompts.py:46` | Neutralisation des balises `mail-non-fiable` et aplatissement des en-têtes contournables par caractères invisibles ou sosies : `<​/mail-non-fiable>`, contrôles bidi, `＜/mail-non-fiable＞` (pleine chasse), caractères « tag » U+E00xx (texte invisible), ` `/` `/`\x85`/`\x0b`/`\x0c` (faux saut de ligne dans l'objet). | **Corrigé** : NFKC, sauts de ligne Unicode → `\n`, suppression des contrôles C0/C1, des caractères de format (catégorie Cf) et des sélecteurs de variante, puis neutralisation des balises. Tests `test_invisible_and_lookalike_tag_variants_neutralized` (9 cas), `test_unicode_line_separators_flattened_in_headers` (5 cas), `test_invisible_payload_characters_removed`. |
| C-03 | MOYEN | `backend/app/claude/runner.py:108` | Une annulation (`CancelledError` : arrêt de l'appli, tâche annulée) pendant l'appel laissait tourner le CLI Claude, avec le jeton OAuth dans son environnement et la consommation de quota. | **Corrigé** : `kill()` du sous-processus sur toute exception non gérée, puis propagation. Test `test_cancellation_kills_child_process`. |
| C-04 | MOYEN | `backend/app/main.py:25`, `:32` | Pas de protection anti-clickjacking (`frame-ancestors`/`X-Frame-Options`). Atténué par `SameSite=Strict` (cookie non envoyé dans un cadre tiers), mais la page de connexion restait encadrable. | **Corrigé** : `frame-ancestors 'self'` dans la CSP et `X-Frame-Options: SAMEORIGIN` (le lecteur `srcdoc` reste fonctionnel). Test `test_anti_clickjacking_headers`. |
| C-05 | MOYEN | `backend/app/auth/routes.py:50-65`, `backend/app/db.py:79-84` | Création du compte non authentifiée tant qu'aucun compte n'existe : si l'appli est exposée avant le premier lancement, un tiers peut s'approprier l'instance (et le jeton Claude de `.env`). Deux `setup` concurrents avec des identifiants différents pouvaient créer deux comptes. | **Corrigé** : (a) vérification + création sous verrou, plus déclencheur SQLite `users_single_row` refusant tout second compte ; (b) `MP_SETUP_TOKEN` optionnel : s'il est défini, `setup` exige `setup_token` (comparaison en temps constant, 403 « Jeton d'installation invalide ») et `/api/auth/status` renvoie `setup_token_required` ; le front affiche alors le champ « Jeton d'installation ». README + `.env.example`. Tests `test_concurrent_setups_create_a_single_user`, `test_second_user_rejected_at_db_level`, `test_setup_token_required_when_configured`, front `setup_sends_install_token_when_required`. |
| C-06 | MOYEN | `backend/app/auth/service.py:19-36`, `routes.py:72-76` | DoS mémoire/CPU non authentifié : chaque tentative de connexion fait un argon2 (64 Mio, paramètres par défaut) ; ~40 requêtes simultanées (pool de threads) avant que le limiteur par IP ne bloque, davantage depuis plusieurs IP. Caddy standard ne fournit pas de limitation de débit. | **Corrigé** : au plus 2 calculs argon2 simultanés (sémaphore global sur hachage et vérification) ; au-delà, attente de 5 s max puis 429 « Trop de tentatives, réessaie dans quelques instants. » (non compté comme échec de connexion). Mots de passe bornés à 256 caractères. Tests `test_password_hashing_concurrency_is_bounded`, `test_concurrent_logins_never_exceed_bound`, `test_busy_hasher_returns_429_without_counting_a_failure`, `test_password_fields_have_max_length`, front `shows_short_wait_message_when_server_busy`. |
| C-07 | MOYEN | `backend/app/claude/prompts.py` (ensemble) | Injection de prompt résiduelle (inhérente aux LLM) : un mail peut influencer sa propre catégorie. | **Accepté** : aucun outil, sortie validée, impact limité à la catégorie/l'alerte, aucune action irréversible automatique. |
| C-08 | FAIBLE | `backend/app/main.py:77` | `/openapi.json`, `/docs`, `/redoc` publiés sans authentification (cartographie de l'API ; contraire à « authentification sur toute l'API »). | **Corrigé** : désactivés. Test `test_openapi_and_docs_not_exposed`. |
| C-09 | FAIBLE | `backend/app/main.py:90` | Réponses `/api/*` sans `Cache-Control` : corps de mails potentiellement conservés dans le cache HTTP du navigateur (appareil partagé, après déconnexion). | **Corrigé** : `Cache-Control: no-store` sur l'API. Test `test_api_responses_are_not_cached`. |
| C-10 | FAIBLE | `docker-compose.yml` | Conteneur avec les capacités Linux par défaut et sans `no-new-privileges`. | **Corrigé** : `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]` ; vérifié à l'exécution (CapEff=0, santé OK). |
| C-11 | FAIBLE | `backend/app/auth/ratelimit.py:12-15` | `X-Forwarded-For` cru si le pair est local ou dans 172.16/12 ; derrière le port publié par Docker, tout client local apparaît en 172.x. Le dernier élément (ajouté par le proxy) est utilisé, donc pas d'usurpation via le proxy ; port lié à `127.0.0.1`. | **Accepté** : à revoir au déploiement NAS si le proxy n'est pas sur la même machine. |
| C-12 | FAIBLE | `backend/app/auth/ratelimit.py` | Verrouillage d'un identifiant après 5 échecs (15 min) : un tiers peut bloquer la connexion du propriétaire ; dictionnaires du limiteur jamais purgés (bornés par le blocage par IP). | **Accepté** (compromis du plan) ; OIDC au plan 2-3. |
| C-13 | FAIBLE | `backend/app/main.py:28` | CSP `style-src 'unsafe-inline'` (nécessaire au `<style>` du `srcdoc` et aux styles inline React). nh3 retire tout `<style>`/`style=` des mails ; pas de `script-src` inline. | **Accepté**. |
| C-14 | FAIBLE | `backend/app/main.py:81-82` | Une exception non gérée produit un 500 texte sans en-têtes de sécurité (le middleware ne voit pas la réponse). Corps fixe « Internal Server Error », sans donnée. | **Accepté**. |
| C-15 | FAIBLE | `backend/app/api/settings_routes.py:98`, `notify/gotify.py:14`, `mail/accounts_routes.py:88`, `mail/imap.py:360` | Requêtes sortantes vers des hôtes choisis par l'utilisateur authentifié (Gotify, IMAP) : SSRF/scan de ports authentifié. Gotify peut être en `http` (jeton en clair sur le LAN). TLS IMAP vérifié (contexte par défaut d'imapclient). | **Accepté** : mono-utilisateur, Gotify est typiquement sur le LAN (liste blanche impossible). |
| C-16 | FAIBLE | `backend/app/notify/webpush.py:97` | `pywebpush`/`requests` suivent les redirections d'un service push autorisé. | **Accepté** : hôtes autorisés = Apple, Google, Mozilla, Microsoft. |
| C-17 | FAIBLE | `backend/app/mail/imap.py:302` | `BODY.PEEK[]` charge le message entier en mémoire (mail de plusieurs dizaines de Mo) avant nettoyage et troncature. | **Reporté plan 2-3** (limite par `RFC822.SIZE`). |
| C-18 | FAIBLE | `backend/app/claude/status.py:58`, `analysis/jobs.py:120` | `last_error` (extrait brut de stderr du CLI) affiché dans les réglages ; le message de `ClaudeBadOutput` journalisé peut contenir un fragment de sortie du modèle. Pas de secret observé. | **Accepté**. |
| C-19 | FAIBLE | `backend/app/crypto.py:9-10` | Clé Fernet = SHA-256 de `MP_SECRET_KEY`, sans sel ni KDF. Acceptable car la clé est exigée ≥ 32 caractères (aléatoire). | **Accepté**. |
| C-20 | FAIBLE | `backend/app/db.py:54`, `data/` | Base SQLite créée en `0644` (hachés, sessions hachées, secrets chiffrés, métadonnées de mails). Conteneur mono-utilisateur ; dépend des droits de `./data` sur l'hôte. | **Accepté** ; README : `./data` propriété de l'utilisateur du conteneur. |
| C-21 | FAIBLE | `Dockerfile:2`, `:9` | Images de base épinglées par tag, pas par empreinte ; `pip 24.0` de l'image a des avis (non utilisé à l'exécution). | **Reporté plan 2-3** (épinglage par digest + mise à jour). |
| C-22 | FAIBLE | `frontend/package.json` | 6 avis npm (2 faibles, 4 modérés) dans la chaîne de build PWA uniquement. | **Accepté** : correctif = rétrogradation cassante de `vite-plugin-pwa` ; à suivre. |
| C-23 | INFO | `.claude/settings.local.json` | AgentShield : pas de bloc `permissions` ni de hook PreToolUse dans la config Claude Code **de dev** du dépôt. | **Accepté** : hors image livrée ; réglage du poste de Mathis. |

### Points vérifiés sans constat

- Mots de passe argon2id, comparaison en temps constant via argon2, hash factice contre l'énumération par timing ; mot de passe ≥ 12, ≤ 256.
- Session : jeton 256 bits aléatoire, stocké haché (SHA-256), cookie `HttpOnly; Secure; SameSite=Strict; Path=/`, nouveau jeton à chaque connexion, suppression à la déconnexion.
- CSRF : en-tête `X-Requested-With: mail-pilot` exigé sur toute méthode non sûre (+ SameSite=Strict, pas de CORS).
- Authentification : toutes les routes hors `/api/health`, `/api/auth/{status,setup,login}` dépendent de `current_user` (routeurs avec `dependencies=[Depends(current_user)]`).
- Erreurs de validation : `input`/`ctx` jamais renvoyés (pas d'écho de secrets).
- SQL : uniquement SQLAlchemy paramétré ; recherche avec `autoescape`.
- Fichiers statiques : résolution + `is_relative_to` (pas de traversée).
- Lecteur : HTML nettoyé par nh3 (liste blanche de balises/attributs, liens http/https/mailto/tel seulement, images distantes retirées), iframe `srcdoc` **sandbox sans `allow-scripts` ni `allow-same-origin`**, `referrerPolicy=no-referrer`, liens en `noopener noreferrer`. Aucun `dangerouslySetInnerHTML` dans le front.
- Service worker : URL de clic des notifications ramenée à la même origine ; aucune mise en cache des réponses `/api`.
- Secrets : `.env` et `data/` ignorés par git et Docker ; aucun secret dans le dépôt ; jeton Gotify et identifiants IMAP chiffrés, jamais renvoyés ; logs sans secret (seul le type d'exception est journalisé pour Gotify/Web Push).
- Jamais de suppression définitive : `uid_expunge` limité à l'UID copié (déplacement).

## Constats différés des revues précédentes

| Constat différé | Statut |
|-----------------|--------|
| T9 FLAG : validateur d'endpoint push laxiste (antislash, espaces, `%`) | C-01, corrigé |
| T7 FLAG : caractères zéro-largeur/format contournant la neutralisation des balises | C-02, corrigé |
| T1 : `CancelledError` laisse le processus enfant | C-03, corrigé |
| T5 : longueur max des mots de passe (DoS argon2) | déjà borné à 256 (login, setup) ; DoS par concurrence → C-06, corrigé |
| T3 : course/absence d'authentification du premier `setup` | C-05, corrigé (verrou + déclencheur, `MP_SETUP_TOKEN`) |
| T3 : X-Forwarded-For | C-11, accepté |
| T15 : CSP `'unsafe-inline'` (styles) | C-13, accepté |
| T15 : 500 sans en-têtes de sécurité | C-14, accepté |
| T10 : `last_error` = stderr brut | C-18, accepté |
| T6/T8/T11/T13 FLAG (dates, mails fantômes, collision léger/complet, UID provisoires, compteurs) | fonctionnels, sans impact de sécurité : hors audit |

## Synthèse

(FAIBLE corrigés : C-08, C-09, C-10 ; la note README n'est pas un constat distinct.)

| Gravité | Trouvés | Corrigés |
|---------|---------|----------|
| CRITIQUE | 0 | 0 |
| ÉLEVÉ | 1 | 1 |
| MOYEN | 6 | 5 |
| FAIBLE | 15 | 3 |
| INFO | 1 | 0 |

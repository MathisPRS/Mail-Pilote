# Mail Pilot

PWA auto-hébergée qui trie ta boîte mail avec Claude (CLI Claude Code en mode headless, via ton abonnement). Un seul conteneur, une seule image, tout l'état dans `./data`.

## Prérequis

- Docker + Docker Compose (image `linux/amd64`)
- Un abonnement Claude (Pro/Max) pour le tri
- Pour chaque boîte : « Se connecter avec Google / Microsoft » (voir plus bas), ou un mot de passe d'application (Gmail, iCloud) ou le mot de passe IMAP (autres fournisseurs)

## Configuration

```bash
cp .env.example .env
python3 -c "import secrets;print(secrets.token_urlsafe(48))"   # à coller dans MP_SECRET_KEY
```

`MP_SECRET_KEY` (32 caractères minimum) chiffre les identifiants mail : l'appli refuse de démarrer sans elle. Si elle est absente ou trop courte, le conteneur s'arrête et le message d'erreur apparaît dans `docker compose logs`. Ne la perds pas et ne la change pas (les boîtes devraient être reconfigurées).

Connexion à Claude : rien à faire dans un terminal. Après le premier lancement, ouvre Réglages › Claude › « Reconnecter », touche « Se connecter à Claude », connecte-toi avec ton compte Claude (abonnement Pro/Max, jamais une clé API) et recopie dans l'appli le code affiché par Claude. L'appli pilote elle-même `claude setup-token` dans le conteneur et enregistre la connexion (valable environ 1 an), chiffrée dans `./data`.

Alternative (avancé) : sur une machine où Claude Code est installé, lance `claude setup-token`, puis colle le jeton obtenu dans `CLAUDE_CODE_OAUTH_TOKEN` du `.env`, ou dans Réglages › Claude › Reconnecter › « Autre méthode (avancé) ».

`./data` doit appartenir à l'utilisateur du conteneur (uid 1000 par défaut). Si ton utilisateur hôte a un autre uid, renseigne `MP_UID` / `MP_GID` dans `.env` (valeurs de `id -u` / `id -g`).

Cet uid n'a pas besoin d'exister dans l'image : le point d'entrée (`docker/entrypoint.sh`) lui fournit une entrée utilisateur fictive via `nss_wrapper` (requise par le CLI Claude, qui lit l'utilisateur courant), avec `HOME=/data/claude-home`.

## Premier lancement

```bash
mkdir -p data          # créé par toi (et non par Docker, qui le créerait en root)
ls -ldn data           # propriétaire = MP_UID:MP_GID du .env (1000:1000 par défaut)
docker compose up -d --build
```

Si `./data` existe déjà avec un autre propriétaire : `sudo chown -R "$(id -u):$(id -g)" data` (avec `MP_UID`/`MP_GID` = `id -u`/`id -g`).

1. Ouvre <http://localhost:8000> (avec `MP_PUBLIC_ORIGIN=http://localhost:8000` dans `.env`).
2. Crée le compte.
3. Connecte Claude : Réglages › Claude › « Reconnecter » (sauf si un jeton est déjà dans `CLAUDE_CODE_OAUTH_TOKEN`).
4. Ajoute une boîte mail : la synchronisation et une première analyse démarrent aussitôt (« Analyse en cours… » en haut à gauche de l'accueil).
5. Pour un tri complet immédiat : bouton Actions › « Lancer une analyse ».

Logs : `docker compose logs -f`. Arrêt : `docker compose down`.

## Connexion Google

Facultatif : sans ces réglages, Gmail reste disponible avec un mot de passe d'application. Avec eux, l'ajout d'une boîte Gmail se fait par la page de connexion officielle de Google (comme Mail sur iPhone), et l'accès se renouvelle tout seul.

1. Ouvre <https://console.cloud.google.com/>, crée un projet (ex. « Mail Pilot »).
2. « API et services › Bibliothèque » : active **Gmail API**.
3. « API et services › Écran de consentement OAuth » (Google Auth Platform) : type **Externe**, nom de l'appli, ton adresse comme contact. Dans « Accès aux données », ajoute le champ d'application `https://mail.google.com/` (plus `openid` et `email`). Ajoute ton adresse dans « Utilisateurs test » pendant les essais.
4. « Identifiants › Créer des identifiants › ID client OAuth » : type **Application Web**. URI de redirection autorisés :
   - `http://localhost:8000/api/oauth/google/callback` (essais en local)
   - puis `https://mail.exemple.fr/api/oauth/google/callback` (ton domaine)
5. Copie l'ID client et le code secret dans `.env` : `GOOGLE_CLIENT_ID=…` et `GOOGLE_CLIENT_SECRET=…`, puis `docker compose up -d`.
6. **Passe l'appli en Production** (« Audience › Publier l'application ») : en mode « Test », Google révoque l'accès au bout de 7 jours. Sans validation Google (inutile pour un usage personnel), la page de connexion affiche « application non validée » : choisis « Paramètres avancés › Accéder à Mail Pilot ».

L'adresse de retour est toujours calculée depuis `MP_PUBLIC_ORIGIN` : elle doit correspondre exactement à l'une des URI déclarées (`http://localhost:8000` en local, ton domaine ensuite).

## Connexion Microsoft

Obligatoire pour Outlook / Hotmail / Live : Microsoft n'accepte plus les mots de passe en IMAP. Le fournisseur « Outlook » n'apparaît dans l'appli qu'une fois ces réglages faits.

1. Ouvre <https://entra.microsoft.com/> (ou le portail Azure) › « Inscriptions d'applications › Nouvelle inscription ».
2. Nom « Mail Pilot » ; types de comptes : **Comptes dans un annuaire organisationnel et comptes Microsoft personnels** ; URI de redirection : plateforme **Web**, `http://localhost:8000/api/oauth/microsoft/callback`.
3. « Authentification » : ajoute aussi `https://mail.exemple.fr/api/oauth/microsoft/callback` quand le domaine est prêt.
4. « Certificats et secrets › Nouveau secret client » : copie la **valeur** (affichée une seule fois ; note sa date d'expiration, à renouveler avant).
5. (Facultatif) « Autorisations de l'API » : ajoute la permission déléguée `IMAP.AccessAsUser.All` (Office 365 Exchange Online), plus `offline_access`, `openid`, `email`. Sinon le consentement est demandé à la première connexion.
6. Dans `.env` : `MS_CLIENT_ID=<ID d'application (client)>`, `MS_CLIENT_SECRET=<valeur du secret>`, `MS_TENANT=common` (ou `consumers` pour les seuls comptes personnels), puis `docker compose up -d`.

Si une boîte affiche « Reconnexion à Google/Microsoft nécessaire » (accès révoqué, mot de passe changé, secret expiré), touche « Se reconnecter » dans Réglages › Boîtes mail.

## Reverse proxy (domaine)

Le port n'est exposé que sur `127.0.0.1:8000`. Place un reverse proxy HTTPS devant, par exemple Caddy (`deploy/Caddyfile.example`) :

```
mail.exemple.fr {
  reverse_proxy 127.0.0.1:8000
}
```

**Crée le compte (premier lancement, sur `localhost`) avant d'activer le reverse proxy** : tant qu'aucun compte n'existe, la page de création est ouverte à quiconque atteint l'appli. Si l'appli doit être exposée avant, renseigne `MP_SETUP_TOKEN` dans `.env` (recommandé) : l'écran de création demande alors ce « jeton d'installation ». Un seul compte peut exister.

Mets alors `MP_PUBLIC_ORIGIN=https://mail.exemple.fr` dans `.env`. Le cookie de session est `Secure` : HTTPS est obligatoire (sauf `localhost`).

## Installation sur l'iPhone

Ouvre l'adresse HTTPS dans Safari › Partager › « Sur l'écran d'accueil ». Les notifications (Web Push) exigent l'appli installée sur l'écran d'accueil (iOS 16.4+), puis activation dans Réglages › Alertes.

## Sauvegarde

Tout l'état est dans `./data` (base SQLite, clés VAPID, jeton Claude chiffré). Sauvegarder = copier ce dossier (arrêter le conteneur pour une copie cohérente). Conserve aussi `MP_SECRET_KEY`.

## Développement local

```bash
# backend
cd backend && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
export MP_SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_urlsafe(48))") DATA_DIR=./data
.venv/bin/uvicorn app.main:create_app --factory --port 8000
.venv/bin/pytest -q

# front (dans un autre terminal) : proxy /api vers localhost:8000
cd frontend && npm ci && npm run dev
npx vitest run
```

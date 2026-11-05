# Mail Pilot

PWA auto-hébergée qui trie ta boîte mail avec Claude (CLI Claude Code en mode headless, via ton abonnement). Un seul conteneur, une seule image, tout l'état dans `./data`.

## Prérequis

- Docker + Docker Compose (image `linux/amd64`)
- Un abonnement Claude (Pro/Max) pour le tri
- Un mot de passe d'application pour chaque boîte (Gmail, iCloud…)

## Configuration

```bash
cp .env.example .env
python3 -c "import secrets;print(secrets.token_urlsafe(48))"   # à coller dans MP_SECRET_KEY
```

`MP_SECRET_KEY` (32 caractères minimum) chiffre les identifiants mail : l'appli refuse de démarrer sans elle. Si elle est absente ou trop courte, le conteneur s'arrête et le message d'erreur apparaît dans `docker compose logs`. Ne la perds pas et ne la change pas (les boîtes devraient être reconfigurées).

Jeton Claude : sur une machine où Claude Code est installé, lance `claude setup-token`, puis colle le jeton dans `CLAUDE_CODE_OAUTH_TOKEN` du `.env`, ou plus tard dans Réglages › Claude.

`./data` doit appartenir à l'utilisateur du conteneur (uid 1000 par défaut). Si ton utilisateur hôte a un autre uid, renseigne `MP_UID` / `MP_GID` dans `.env` (valeurs de `id -u` / `id -g`).

## Premier lancement

```bash
docker compose up -d --build
```

1. Ouvre <http://localhost:8000> (avec `MP_PUBLIC_ORIGIN=http://localhost:8000` dans `.env`).
2. Crée le compte.
3. Ajoute une boîte mail.
4. Colle le jeton Claude dans Réglages › Claude (sauf s'il est déjà dans `CLAUDE_CODE_OAUTH_TOKEN`).
5. Lance une analyse.

Logs : `docker compose logs -f`. Arrêt : `docker compose down`.

## Reverse proxy (domaine)

Le port n'est exposé que sur `127.0.0.1:8000`. Place un reverse proxy HTTPS devant, par exemple Caddy (`deploy/Caddyfile.example`) :

```
mail.exemple.fr {
  reverse_proxy 127.0.0.1:8000
}
```

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

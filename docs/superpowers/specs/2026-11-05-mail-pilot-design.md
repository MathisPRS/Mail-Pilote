# Mail Pilot — document de conception

*Date : 2026-11-05 · Statut : à valider par Mathis*

Maquettes validées (cliquables) : https://claude.ai/artifact/35dhAH8cbusRqv7baBmftR

---

## 1. Intention

Mathis ne veut plus surveiller ses boîtes mail. Claude lit ses mails à sa place, plusieurs fois par jour, trie, nettoie la pub et le spam, et **ne le dérange que lorsqu'un mail mérite vraiment d'être lu** — en particulier quand un **TT+** (jour de télétravail supplémentaire) est annoncé.

L'outil apprend de ses habitudes : ce qu'il ouvre, ce qu'il supprime sans lire, ce qu'il garde. Chaque soir, Claude met à jour ses règles de tri pour que les analyses suivantes soient plus justes.

Contrainte de départ : l'utilisateur est sur iPhone et ne veut pas payer le compte développeur Apple. L'application est donc une **PWA** (web app installée sur l'écran d'accueil via Safari), auto-hébergée sur son **NAS**.

### Ce qui fait le succès
- Il ouvre ses mails seulement quand une alerte le lui demande.
- Aucun mail important n'est perdu (ni supprimé à tort, ni noyé).
- L'alerte TT+ arrive à temps.
- Le tri s'améliore visiblement au fil des semaines, sans qu'il ait à tout configurer.

### Non-objectifs
- Pas de client mail complet : pas de rédaction ni d'envoi de mails depuis l'appli (on ouvre l'app mail native pour lire ou répondre).
- Pas d'application native iOS / App Store.
- Pas de multi-utilisateur : un seul utilisateur (Mathis).

### Anti-objectifs (échec même si « ça marche »)
- Un mail légitime supprimé définitivement.
- Claude qui exécute une action dictée par le contenu d'un mail (injection de prompt).
- Des notifications trop fréquentes qui obligent à re-surveiller l'appli.
- Des identifiants mail stockés en clair.

---

## 2. Contraintes

| Sujet | Contrainte |
|---|---|
| Plateforme cliente | PWA iPhone (Safari, iOS ≥ 16.4 pour le Web Push), utilisable aussi sur desktop |
| Hébergement | NAS personnel monté à la main sous **Debian** (x86_64 supposé), Docker |
| Conteneur | **Une seule image Docker, un seul conteneur** contenant front, back et base de données ; `docker-compose` avec un seul service |
| Claude | **Abonnement Claude Max 5x, en mode headless** (Claude Code CLI / Agent SDK) — **pas de clé API** |
| Fournisseurs mail | Gmail, Outlook (perso), iCloud, IMAP générique (La Poste, Free, Orange…) |
| Accès réseau | **Domaine personnel** en HTTPS (requis pour le Web Push et les passkeys/Face ID). L'appli est donc **exposée sur Internet** : l'authentification est obligatoire dès la V1. |
| Délais | Alerte d'un mail important ou TT+ **dans l'heure** ; tri complet **3 à 4 fois par jour** |
| Langue | Interface en français |

---

## 3. Ce qui a été décidé

### 3.1 Interface (validée sur maquettes)

Navigation sans barre d'onglets ; tout part de l'accueil, avatar en haut à droite.

1. **Accueil « Mes boîtes »** (écran d'ouverture)
   - Une grande carte par boîte configurée + une carte « Toutes les boîtes » (vue unifiée) en premier.
   - Chaque carte : nom, adresse, pastille du nombre de **non-lus** (réception), et les **2 derniers mails « à ne pas manquer »**.
   - « + Ajouter une boîte mail ».
   - En-tête : état Claude (« analysé à 08:00 »), bouton **Actions** (éclair), **avatar** → Profil.
2. **Liste des mails** (après clic sur une carte)
   - Retour « ‹ Boîtes ». Titre = dossier courant, sous-titre = boîte ; clic sur le titre → **choix du dossier**.
   - Recherche, puis **filtres par catégorie** (Tout, Important, À traiter, TT+, Infos, Newsletters, Pub, Spam) avec compteurs.
   - **Encadré « À ne pas manquer »** en tête de liste (3 lignes, compteur) ; un clic filtre sur les mails prioritaires, un second clic revient à tout. L'encadré défile avec la liste (seuls titre / recherche / filtres restent fixes).
   - Lignes compactes façon Mail iOS : point bleu non-lu, couleur de la boîte, expéditeur, heure, objet, aperçu 2 lignes précédé d'une étiquette de catégorie.
   - Clic sur un mail → actions : Ouvrir (dans l'app mail native), Archiver, Important, Corbeille. Toute action destructive affiche « Annuler ».
   - Bouton **Sélectionner** → sélection multiple (cases, tout sélectionner, barre du bas : Lu, Important, Déplacer, Archiver, Corbeille).
3. **Choix du dossier** (panneau du bas) : Réception, Brouillons, Envoyés, Indésirables, Archives, Corbeille + dossiers personnels de la boîte. **Récupérés automatiquement** sur chaque serveur ; vue unifiée pour « Toutes les boîtes ».
4. **Actions manuelles** (panneau du bas) : Lancer une analyse, Nettoyer pubs et spams (annulable), Lancer l'apprentissage.
5. **Profil** (avatar) : liste de boutons simples, sans élément non fonctionnel.
   - *Compte* : nom affiché, e-mail de contact, fuseau horaire.
   - *Mot de passe et sécurité* : **Face ID** (déverrouillage + délai : aussitôt / 5 min / 1 h / 4 h), changement de mot de passe, appareils connectés, déconnexion des autres appareils.
   - *Thème* : automatique / clair / sombre.
   - *Boîtes mail* : état par boîte (synchronisée / erreur + correction), interrupteur « analyser cette boîte », ajout guidé par fournisseur.
   - *Claude* : état, **jours restants avant expiration du login**, dernier appel réussi, **Reconnecter**, alerte 7 jours avant expiration.
   - *Règles de tri* : suggestions apprises à valider/refuser, règles de l'utilisateur, ajout.
   - *Planification* : horaires d'analyse (ajout/retrait), jours actifs, heure de l'apprentissage du soir.
   - *Alertes* : Notification iPhone, Gotify (URL, jeton, test), types d'alerte, heures de silence (+ « TT+ passe quand même »).

### 3.2 Architecture

```
[iPhone PWA] ──HTTPS (domaine perso)──> [reverse proxy TLS] ──> [conteneur unique « mail-pilot »]
                                                                  ├─ API FastAPI (+ sert le front PWA compilé)
                                                                  ├─ Planificateur (vérif. légère, tri complet, apprentissage)
                                                                  ├─ Connecteurs mail (IMAP, OAuth Microsoft)
                                                                  ├─ Moteur Claude (Claude Code headless, abonnement)
                                                                  ├─ Notifications (Web Push, Gotify)
                                                                  └─ SQLite (+ skill de tri versionné)
                                                                volume /data : base, skill, session Claude, clés
```

- **Backend** : Python, FastAPI, planificateur intégré (APScheduler ou équivalent).
- **Front** : React (Vite) en PWA (manifest, service worker, Web Push), compilé et servi par FastAPI.
- **Base de données** : SQLite dans le même conteneur (aucun serveur de base séparé), fichier sur le volume `/data`.
- **Image** : un `Dockerfile` multi-étapes (étape Node qui compile le front → image finale Python + runtime de Claude Code), un seul processus applicatif. Un `docker-compose.yml` avec **un seul service**, un volume `/data`, un fichier `.env` (clé de chiffrement, domaine).
- Tout l'état persistant est dans `/data` : on peut recréer le conteneur sans rien perdre, et la sauvegarde se résume à copier ce dossier.

### 3.3 Connexion aux boîtes mail

| Fournisseur | Méthode |
|---|---|
| Gmail | IMAP + mot de passe d'application (validation en 2 étapes requise) |
| iCloud | IMAP + mot de passe pour app |
| IMAP générique (La Poste…) | IMAP : serveur, port (993), mot de passe |
| Outlook perso | **OAuth2 Microsoft** (l'authentification par mot de passe est désactivée chez Microsoft) — application gratuite à déclarer côté Microsoft, guidée dans l'appli |

- Ajout d'un compte à chaud depuis l'interface avec « Tester la connexion » avant enregistrement.
- Dossiers : détectés automatiquement via les attributs « special-use » IMAP (Brouillons, Envoyés, Indésirables, Corbeille, Archives), avec repli sur les noms usuels si le serveur ne les annonce pas. Les autres dossiers = dossiers personnels.
- Identifiants et jetons **chiffrés au repos** (clé fournie par variable d'environnement, hors base).

### 3.4 Sessions d'analyse

Deux niveaux :

- **Vérification légère** toutes les **30 minutes** (de 07:00 à 23:00 par défaut) : récupère uniquement expéditeur + objet des nouveaux mails, applique les règles déterministes, puis — seulement s'il y a des mails non tranchés — un appel court à Claude **sur les objets uniquement**. Objectif : envoyer les alertes **TT+ / Important / À traiter dans l'heure**. Rien n'est supprimé à ce niveau. S'il n'y a aucun nouveau mail, aucun appel à Claude.
- **Tri complet** : défaut **4 fois par jour** (08:00 / 12:00 / 16:00 / 20:00, Europe/Paris, horaires et jours configurables) + déclenchement manuel. C'est lui qui lit les corps si besoin, résume, catégorise définitivement et applique les règles de nettoyage.

Détails du tri complet :
- **Incrémentales** : seuls les nouveaux mails depuis la session précédente.
- **Lecture en deux temps** : Claude reçoit d'abord expéditeur + objet de tous les nouveaux mails ; il ne lit le corps que lorsque c'est nécessaire pour trancher ou résumer (économie d'abonnement).
- Pour chaque mail, Claude rend un **résultat structuré** : catégorie, prioritaire oui/non, raison courte, résumé d'une ligne, échéance éventuelle, détection TT+ (+ date du TT+).
- **Claude n'a aucun outil d'action.** Il classe ; c'est le backend qui applique les actions selon les règles. Le contenu des mails est passé comme donnée non fiable, jamais comme instruction.
- Si Claude est déconnecté, la session est mise en attente et rejouée après reconnexion ; l'utilisateur est alerté.

### 3.5 Catégories et actions

- Catégories : **TT+**, **Important**, **À traiter**, Infos, Newsletters, Pub, Spam.
- « À ne pas manquer » = TT+ + Important + À traiter.
- Actions automatiques possibles uniquement via une **règle validée** (règle utilisateur ou suggestion apprise acceptée) : corbeille, marquer important, alerte TT+.
- **Jamais de suppression définitive** : tout passe par la corbeille du fournisseur ; chaque action est journalisée et annulable depuis l'appli.
- Les règles de l'utilisateur priment sur ce que Claude apprend.

### 3.6 Apprentissage

- **Observation** : à chaque synchronisation, le backend compare l'état des mails avec la synchronisation précédente et en déduit les gestes faits *depuis n'importe quel client* (iPhone, webmail…) : ouvert, supprimé sans être ouvert, supprimé après lecture, déplacé, marqué, répondu. S'y ajoutent les actions faites dans l'appli. Tout est écrit dans un **journal de comportement**.
- **Apprentissage du soir** (défaut 23:00, désactivable, lançable à la main) : Claude relit le journal du jour et :
  1. met à jour un **skill de tri** en français clair (fichier versionné), utilisé par toutes les sessions suivantes ;
  2. produit des **suggestions de règles** (« Tu supprimes Promo Mode sans les ouvrir (12 fois) → corbeille automatique ? ») qui n'agissent qu'après validation dans l'appli.
- Pour apprendre, Claude ne voit que des **métadonnées** (expéditeur, domaine, objet, catégorie attribuée, geste) — jamais le corps des mails — afin qu'un mail piégé ne puisse pas écrire de règle.
- Les versions du skill sont conservées (historique, retour arrière).
- **Démarrage à froid** : à l'ajout d'une boîte, analyse de l'historique existant (mails lus / jamais lus / supprimés) pour amorcer le skill.

### 3.7 Règles utilisateur

Trois types : **Expéditeur** (adresse ou domaine), **Type de mail** (ex. factures), **Contexte** (texte libre, ex. « tout ce qui concerne l'école »). Trois effets : **Important**, **Alerte TT+**, **Corbeille**.

### 3.8 Alertes

- Canaux : **Web Push** (PWA installée) et **Gotify** ; chacun activable.
- Types : TT+, Important, À traiter, résumé après chaque analyse (désactivé par défaut).
- Une notification = titre court + raison en une ligne ; clic → le mail dans l'appli.
- **Heures de silence** (défaut 22:00–07:00), avec option « TT+ passe quand même ».

### 3.9 Connexion à Claude

- Claude Code tourne en headless dans le conteneur, authentifié avec l'**abonnement** de l'utilisateur. Privilégier un jeton longue durée lié à l'abonnement (de type `claude setup-token`) pour limiter les déconnexions — à vérifier sur le compte réel.
- L'appli affiche l'état, la **date d'expiration / jours restants**, le dernier appel réussi ; contrôle de santé périodique peu coûteux.
- **Reconnexion** guidée depuis l'appli. Alerte 7 jours avant expiration et immédiatement en cas d'échec d'authentification.

### 3.10 Sécurité et accès

- L'appli est accessible par un **domaine personnel** en HTTPS, donc **exposée sur Internet**. Le domaine est fixé avant la mise en service : il sert d'identifiant aux passkeys et d'adresse de retour pour la connexion Microsoft.
- **Authentification obligatoire dès la V1** : compte unique, mot de passe local (haché), sessions avec expiration, protection contre les essais répétés (limitation et blocage temporaire), cookies sécurisés.
- Déverrouillage **Face ID** via **passkey (WebAuthn)**, délai de verrouillage configurable ; le mot de passe reste le secours.
- Premier démarrage : création du compte depuis l'appli, seulement si aucun compte n'existe encore.
- **OIDC** : prévu dans le code (désactivé par défaut, activable par configuration), non visible dans l'interface tant qu'il n'est pas configuré.
- Aucun élément non terminé n'apparaît dans l'interface.

---

## 4. Choix faits par Claude (à vérifier par Mathis)

- **Lire un mail depuis une alerte** : iOS ne permet pas d'ouvrir *un* mail précis dans Mail / Gmail / Outlook depuis une web app. L'appli affiche donc le mail dans une **vue de lecture simple, en lecture seule** (contenu nettoyé, pièces jointes listées), avec le résumé de Claude en tête et un bouton « Ouvrir l'app [fournisseur] ». Ni rédaction ni réponse (le non-objectif « pas de client mail complet » reste valable).
- **Nettoyage manuel pubs/spams** : c'est une action déclenchée par l'utilisateur, donc elle n'a pas besoin de règle validée. Elle affiche le nombre de mails concernés, va en corbeille et reste annulable. Les actions *automatiques* restent limitées aux règles validées.
- **Écriture côté serveur mail** : l'appli ne fait que lire, marquer comme lu, déplacer (archives, corbeille, dossiers) et marquer d'un drapeau. Les catégories de Claude restent **internes à l'appli** : elles ne créent ni dossiers ni libellés chez le fournisseur.
- **Apprentissage et actions de l'appli** : chaque action faite par l'appli est journalisée avec sa source pour que l'observateur ne la confonde pas avec un geste de Mathis (l'appli n'apprend pas de ses propres actions).
- **Démarrage à froid** : analyse des **90 derniers jours**, par lots, à faible priorité, interrompue si la limite d'usage approche. Les métadonnées seules (expéditeur, objet, lu/non lu, dossier) suffisent pour amorcer le skill.
- **Limite d'usage Claude atteinte** : la session est mise en file et rejouée plus tard. Le pré-tri par règles déterministes (expéditeurs connus, règles utilisateur) continue sans Claude. Les alertes TT+ et les règles « Important » restent assurées.
- **Vérification de la connexion headless** : c'est la toute première tâche de développement (prototype jetable). Si le jeton longue durée ne fonctionne pas dans un conteneur, on revoit la section 3.9 avant d'aller plus loin.
- **Gotify** : utilisé s'il existe déjà (URL + jeton saisis dans l'appli). Il n'est pas embarqué, pour garder un seul conteneur.
- **HTTPS** : le conteneur sert en HTTP sur un port interne ; le certificat TLS est géré par un reverse proxy devant (celui déjà en place sur le NAS, ou Caddy/Traefik si aucun n'existe). Un exemple de configuration est fourni.
- **Processeur** : image construite pour x86_64 (amd64), comme sur un PC Debian classique ; une variante ARM sera possible si besoin.
- **Rythme** : tri complet 4 fois par jour par défaut (dans la fourchette 3–4 demandée), vérification légère toutes les 30 minutes. L'abonnement Max 5x permet ce rythme ; l'usage est suivi pour l'ajuster.

## 5. Outils de développement

- **Génération de code** : plugin **Superpowers** (`obra/superpowers`, ~313 k étoiles GitHub, déjà installé). Déroulé : conception → plan d'implémentation → développement par sous-agents avec tests d'abord (TDD) et relecture de code à chaque tâche.
- **Sécurité** : **ECC** (`affaan-m/ECC`, ~298 k étoiles), installé **au niveau du projet**, utilisé pour :
  - l'agent `security-reviewer` et le skill `security-review` (OWASP Top 10, secrets, injections, authentification) à la fin de chaque phase et avant la mise en production ;
  - les règles de sécurité Python et TypeScript ;
  - **AgentShield** (`/security-scan`) pour auditer la configuration de Claude embarquée dans le conteneur (prompts, permissions, hooks) — point sensible puisque Claude lit des mails non fiables.
- ECC sert uniquement à la sécurité : son propre déroulé de développement n'est pas activé, pour ne pas faire doublon avec Superpowers.

## 6. Laissé au constructeur

- Choix des bibliothèques (IMAP, OAuth Microsoft, Web Push, WebAuthn, planificateur), schéma de la base, structure du code.
- Format exact du résultat structuré de Claude et du skill de tri.
- Fréquence de synchronisation légère entre deux analyses (pour l'observation des gestes et les compteurs).
- Format des sauvegardes et du journal d'audit.
- Découpage en phases de développement, en priorisant : connexion boîtes + analyse + accueil/liste + alertes, puis apprentissage, puis sécurité Face ID.

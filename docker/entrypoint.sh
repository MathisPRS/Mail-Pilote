#!/bin/sh
# Point d'entrée du conteneur.
#
# Le conteneur tourne sous l'uid de l'hôte (MP_UID/MP_GID, propriétaires de ./data). Cet uid n'a
# en général aucune entrée dans /etc/passwd de l'image : os.userInfo() du CLI Claude (Node) lève
# alors ENOENT et le tri échoue. On fournit une entrée fictive via nss_wrapper (sans root, sans
# modifier /etc/passwd), puis on exécute la commande (CMD).
set -eu

uid=$(id -u)
gid=$(id -g)

if ! getent passwd "$uid" >/dev/null 2>&1; then
  home="${DATA_DIR:-/data}/claude-home"
  dir=$(mktemp -d /tmp/mp-nss.XXXXXX)
  cp /etc/passwd "$dir/passwd"
  printf 'mailpilot-%s:x:%s:%s:Mail Pilot:%s:/usr/sbin/nologin\n' "$uid" "$uid" "$gid" "$home" >> "$dir/passwd"
  cp /etc/group "$dir/group"
  if ! getent group "$gid" >/dev/null 2>&1; then
    printf 'mailpilot-%s:x:%s:\n' "$gid" "$gid" >> "$dir/group"
  fi
  export LD_PRELOAD=libnss_wrapper.so NSS_WRAPPER_PASSWD="$dir/passwd" NSS_WRAPPER_GROUP="$dir/group"
  export HOME="$home"
fi

exec "$@"

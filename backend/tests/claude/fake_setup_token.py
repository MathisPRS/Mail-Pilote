#!/usr/bin/env python3
"""Faux `claude` pour les tests : imite `claude setup-token` (Claude Code 2.1.x) dans un pseudo-terminal.

Options (avant `setup-token`) :
  --host HOST        hôte du lien affiché (défaut claude.com)
  --env-dump PATH    écrit l'environnement reçu (JSON) dans PATH
  --pid-file PATH    écrit le pid dans PATH
  --no-url           n'affiche jamais de lien (test du délai de démarrage)

Code reçu : « good… » -> faux jeton d'abonnement ; « hang » -> ne répond plus ;
« exit » -> quitte sans rien dire ; autre -> message d'erreur.
"""
import json
import os
import sys
import time

ESC = "\x1b"
BEL = "\x07"
FAKE_TOKEN = "sk-ant-oat01-FAKE_token-0123456789abcdefABCDEF"


def main() -> int:
    args = sys.argv[1:]
    host = "claude.com"
    no_url = False
    while args and args[0].startswith("--"):
        opt = args.pop(0)
        if opt == "--host":
            host = args.pop(0)
        elif opt == "--env-dump":
            with open(args.pop(0), "w") as f:
                json.dump(dict(os.environ), f)
        elif opt == "--pid-file":
            with open(args.pop(0), "w") as f:
                f.write(str(os.getpid()))
        elif opt == "--no-url":
            no_url = True
    if args != ["setup-token"]:
        print("usage: claude setup-token", file=sys.stderr)
        return 2
    out = sys.stdout
    if not (sys.stdin.isatty() and out.isatty()):
        print("Raw mode is not supported", file=sys.stderr)
        return 1
    out.write(f"{ESC}[2J{ESC}[H{ESC}[1m✻ Welcome to Claude Code{ESC}[0m\r\n\r\n")
    out.write("Opening browser to sign in…\r\n")
    # spinner verbeux : le lecteur doit vider le pseudo-terminal en continu
    for i in range(2000):
        out.write(f"{ESC}[2K\r{'⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'[i % 10]} Waiting for browser…")
    out.flush()
    if no_url:
        time.sleep(3600)
        return 0
    url = (
        f"https://{host}/cai/oauth/authorize?code=true&client_id=abc&response_type=code"
        "&redirect_uri=https%3A%2F%2Fplatform.claude.com%2Foauth%2Fcode%2Fcallback"
        "&scope=user%3Ainference&code_challenge=CHALLENGE&code_challenge_method=S256&state=STATE"
    )
    out.write(f"\r\n{ESC}[2mBrowser didn't open? Use the url below to sign in (c to copy){ESC}[0m\r\n\r\n")
    # lien OSC 8, découpé en morceaux répétés comme Ink le fait au retour à la ligne
    for part in (url[:60], url[60:120], url[120:]):
        out.write(f"{ESC}]8;id=link1;{url}{BEL}{ESC}[34m{part}{ESC}[39m{ESC}]8;;{BEL}\r\n")
    out.write(f"\r\n{ESC}]8;id=link2;{url}{ESC}\\{url}{ESC}]8;;{ESC}\\\r\n")
    out.write("\r\nPaste code here if prompted > ")
    out.flush()
    code = sys.stdin.readline().strip()
    if code.startswith("good"):
        out.write(f"\r\n{ESC}[32m✓ Long-lived authentication token created successfully!{ESC}[0m\r\n\r\n")
        out.write(f"Your OAuth token (valid for 1 year):\r\n\r\n{ESC}[1m{FAKE_TOKEN}{ESC}[0m\r\n\r\n")
        out.write("Store this token securely. You won't be able to see it again.\r\n")
        out.flush()
        return 0
    if code == "hang":
        time.sleep(3600)
        return 0
    if code == "exit":
        return 1
    out.write(f"\r\n{ESC}[31mOAuth error: Invalid code. Please make sure the full code was copied{ESC}[0m\r\n")
    out.flush()
    time.sleep(3600)  # le vrai CLI peut rester ouvert après une erreur
    return 1


if __name__ == "__main__":
    sys.exit(main())

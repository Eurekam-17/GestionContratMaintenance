"""Garde-fou environnement Odoo — Eurekam Maintenance.

Ce script DOIT etre execute avant toute autre operation visant la base Odoo
(installation/maj du module, import, modification de donnees, lancement des tests).

Verifications effectuees :
    1. Le fichier config/odoo_test.json existe et est lisible.
    2. Le champ "environment" vaut bien "TEST".
    3. L'URL contient au moins un mot-cle de test (test, staging, dev, preprod).
    4. L'URL ne contient AUCUN mot-cle interdit (prod, production, main, ...).
    5. La connexion XML-RPC a Odoo aboutit et la version serveur est lisible.
    6. Le nom de base reel correspond a celui declare dans la config.
    7. L'authentification reussit avec les credentials fournis.

En cas d'echec d'une de ces verifications, le script s'arrete avec un code != 0
et toute operation appelante doit etre annulee.

Usage :
    python scripts/00_check_environment.py
    python scripts/00_check_environment.py --config config/odoo_test.json
    python scripts/00_check_environment.py --quiet   (n'affiche que les erreurs)
"""

from __future__ import annotations

import argparse
import json
import sys
import xmlrpc.client
from pathlib import Path

# Codes de sortie
EXIT_OK = 0
EXIT_CONFIG_MISSING = 10
EXIT_CONFIG_INVALID = 11
EXIT_ENV_NOT_TEST = 20
EXIT_URL_NOT_TEST = 21
EXIT_URL_FORBIDDEN = 22
EXIT_CONNECTION_FAILED = 30
EXIT_DB_MISMATCH = 31
EXIT_AUTH_FAILED = 32

DEFAULT_TEST_KEYWORDS = ("test", "staging", "dev", "preprod")
DEFAULT_FORBIDDEN_KEYWORDS = ("prod", "production", "main")


def log(message: str, *, quiet: bool = False) -> None:
    if not quiet:
        print(message)


def fail(message: str, code: int) -> None:
    """Affiche le message d'erreur et termine avec le code donne."""
    print(message, file=sys.stderr)
    sys.exit(code)


def load_config(config_path: Path) -> dict:
    """Charge le fichier de configuration JSON."""
    if not config_path.exists():
        fail(
            f"X STOP : fichier de configuration introuvable : {config_path}\n"
            f"  -> Copier config/odoo_test.json.example vers {config_path.name} "
            f"et y renseigner les credentials de la base de TEST.",
            EXIT_CONFIG_MISSING,
        )

    try:
        with config_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        fail(
            f"X STOP : fichier de configuration JSON invalide ({config_path}) : {exc}",
            EXIT_CONFIG_INVALID,
        )
    except OSError as exc:
        fail(
            f"X STOP : impossible de lire {config_path} : {exc}",
            EXIT_CONFIG_INVALID,
        )


def check_environment_field(config: dict) -> None:
    """Verifie que le champ 'environment' vaut TEST."""
    env = config.get("environment")
    if env != "TEST":
        fail(
            f"X STOP : le champ 'environment' doit etre 'TEST' (valeur actuelle : {env!r}).\n"
            f"  -> Refuser tout demarrage sur une configuration qui ne declare pas explicitement TEST.",
            EXIT_ENV_NOT_TEST,
        )


def check_url(config: dict) -> str:
    """Verifie que l'URL ressemble a une base de test et ne contient aucun mot interdit."""
    url = config.get("url", "").strip()
    if not url:
        fail("X STOP : champ 'url' manquant ou vide dans la configuration.", EXIT_CONFIG_INVALID)

    url_lower = url.lower()
    safety = config.get("safety_check", {}) or {}

    # 1. Mots-cles de test obligatoires
    if safety.get("require_test_in_url", True):
        if not any(kw in url_lower for kw in DEFAULT_TEST_KEYWORDS):
            fail(
                f"X STOP : l'URL {url!r} ne contient aucun mot-cle de test "
                f"({', '.join(DEFAULT_TEST_KEYWORDS)}).\n"
                f"  -> Refuser de continuer : risque de viser la production.",
                EXIT_URL_NOT_TEST,
            )

    # 2. Mots-cles interdits
    forbidden = safety.get("forbidden_url_keywords", DEFAULT_FORBIDDEN_KEYWORDS)
    for mot in forbidden:
        # On ignore les mots interdits qui sont eux-memes presents dans un mot autorise
        # ex: 'preprod' contient 'prod' -> on traite ce cas en verifiant les frontieres
        mot_lower = mot.lower()
        if mot_lower in url_lower:
            # Cas particulier : 'prod' present dans 'preprod' -> autorise
            if mot_lower == "prod" and "preprod" in url_lower:
                continue
            fail(
                f"X STOP : l'URL {url!r} contient le mot-cle interdit {mot!r}.\n"
                f"  -> Risque de cibler la production. Operation annulee.",
                EXIT_URL_FORBIDDEN,
            )

    return url


def check_odoo_connection(config: dict, url: str, *, quiet: bool = False) -> dict:
    """Se connecte au serveur Odoo et verifie que la base correspond."""
    expected_db = config.get("database", "").strip()
    if not expected_db:
        fail("X STOP : champ 'database' manquant ou vide dans la configuration.", EXIT_CONFIG_INVALID)

    try:
        common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common", allow_none=True)
        version_info = common.version()
    except (xmlrpc.client.Fault, xmlrpc.client.ProtocolError, ConnectionError, OSError) as exc:
        fail(
            f"X STOP : connexion XML-RPC echouee sur {url} : {exc}\n"
            f"  -> Verifier l'URL, la connectivite reseau et que le serveur Odoo repond.",
            EXIT_CONNECTION_FAILED,
        )

    server_version = version_info.get("server_version", "?")
    log(f"OK Connexion XML-RPC reussie. Version serveur : {server_version}", quiet=quiet)

    # Authentification : on accepte 'password' (mot de passe utilisateur OU cle API)
    # ou l'ancien champ 'api_key' pour retrocompatibilite. Odoo XML-RPC traite
    # les deux de la meme maniere via common.authenticate().
    username = config.get("username", "").strip()
    secret = (config.get("password") or config.get("api_key") or "").strip()
    if not username:
        fail("X STOP : 'username' manquant dans la configuration.", EXIT_CONFIG_INVALID)
    if not secret:
        fail(
            "X STOP : 'password' (ou 'api_key') manquant dans la configuration.",
            EXIT_CONFIG_INVALID,
        )

    placeholders = {
        "REMPLACER_PAR_LE_MOT_DE_PASSE_OU_LA_CLE_API",
        "REMPLACER_PAR_LA_CLE_API_DE_TEST",
    }
    if secret in placeholders:
        fail(
            "X STOP : la valeur d'authentification est encore la valeur exemple. "
            "Renseigner le vrai mot de passe (ou cle API) de TEST dans config/odoo_test.json.",
            EXIT_CONFIG_INVALID,
        )

    try:
        uid = common.authenticate(expected_db, username, secret, {})
    except (xmlrpc.client.Fault, xmlrpc.client.ProtocolError, ConnectionError, OSError) as exc:
        fail(
            f"X STOP : authentification echouee sur la base {expected_db!r} : {exc}",
            EXIT_AUTH_FAILED,
        )

    if not uid:
        fail(
            f"X STOP : authentification refusee pour {username!r} sur la base {expected_db!r}.\n"
            f"  -> Verifier l'utilisateur, la cle API et le nom exact de la base.",
            EXIT_AUTH_FAILED,
        )

    log(f"OK Authentification reussie (uid={uid}) sur la base {expected_db!r}.", quiet=quiet)
    return {"version": version_info, "uid": uid, "database": expected_db}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Garde-fou environnement Odoo (Eurekam Maintenance) — verifie qu'on cible bien la base de TEST."
    )
    parser.add_argument(
        "--config",
        default="config/odoo_test.json",
        help="Chemin vers le fichier de configuration (defaut: config/odoo_test.json)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="N'affiche que les erreurs (utile dans les scripts batch).",
    )
    parser.add_argument(
        "--skip-connection",
        action="store_true",
        help="Saute les verifications reseau (utile pour tester la config seule).",
    )
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    config = load_config(config_path)

    check_environment_field(config)
    url = check_url(config)

    log("", quiet=args.quiet)
    log("=" * 60, quiet=args.quiet)
    log(f">> ENVIRONNEMENT : TEST  --  Base : {config.get('database')}", quiet=args.quiet)
    log(f">> URL           : {url}", quiet=args.quiet)
    log("=" * 60, quiet=args.quiet)

    if args.skip_connection:
        log("(--skip-connection) verifications reseau ignorees.", quiet=args.quiet)
        log("OK Verifications de configuration OK.", quiet=args.quiet)
        return EXIT_OK

    info = check_odoo_connection(config, url, quiet=args.quiet)

    log("", quiet=args.quiet)
    log("OK Toutes les verifications sont passees. Vous pouvez continuer.", quiet=args.quiet)
    log(
        f"   (base={info['database']}, uid={info['uid']}, "
        f"server_version={info['version'].get('server_version')})",
        quiet=args.quiet,
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

"""Genera configuración privada con entrada de contraseña oculta.

Uso: python -m cloud.setup --url https://DOMINIO_REAL
El archivo .env.cloud queda fuera de Git. No imprime secretos.
"""
from __future__ import annotations

import argparse
from getpass import getpass
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit

from werkzeug.security import generate_password_hash


def main() -> None:
    parser = argparse.ArgumentParser(description='Configura Corte privado en la nube.')
    parser.add_argument('--url', required=True, help='Origen HTTPS del servicio, sin ruta.')
    parser.add_argument('--output', default='.env.cloud')
    args = parser.parse_args()
    url = args.url.rstrip('/')
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        parser.error('Usa un origen HTTPS sin ruta ni parámetros.')
    target = Path(args.output).resolve()
    if target.exists():
        parser.error('El archivo ya existe; no se reemplazan llaves maestras existentes.')
    password = getpass('Nueva contraseña de Corte (mínimo 14 caracteres): ')
    if len(password) < 14 or len(password) > 1024:
        parser.error('La contraseña debe tener entre 14 y 1024 caracteres.')
    if not secrets.compare_digest(password, getpass('Repite la contraseña: ')):
        parser.error('Las contraseñas no coinciden.')
    lines = [f'CORTE_PUBLIC_URL={url}', 'CORTE_AUTH_PROVIDER=password',
             f'CORTE_PASSWORD_HASH={generate_password_hash(password)}',
             f'CORTE_SESSION_SECRET={secrets.token_urlsafe(48)}',
             f'CORTE_ENCRYPTION_KEY={secrets.token_urlsafe(48)}', 'CORTE_TRUST_PROXY=1']
    with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as output:
        output.write('\n'.join(lines) + '\n')
    print(f'Configuración privada creada en {target}. No la subas a Git ni la compartas en el chat.')


if __name__ == '__main__':
    main()

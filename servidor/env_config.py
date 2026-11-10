"""Configuração local sincronizada com o painel. Nunca enviada ao navegador."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parents[1] / '.env'
_lock = threading.RLock()


def read() -> dict[str, str]:
    if not ENV_PATH.exists():
        return {}
    result = {}
    for line in ENV_PATH.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key, value = key.strip().removeprefix('export '), value.strip()
        if value.startswith('"'):
            try: value = json.loads(value)
            except ValueError: continue
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        else:
            value = value.split(' #', 1)[0].strip()
        if isinstance(value, str):
            result[key] = value
    return result


def update(values: dict) -> None:
    """Atualização atômica; preserva chaves de outras integrações."""
    with _lock:
        data = read()
        data.update({k: str(v) for k, v in values.items()})
        ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = ENV_PATH.with_suffix('.env.tmp')
        try:
            with temporary.open('w', encoding='utf-8') as file:
                file.write('# Credenciais locais do Sorteador Geral. Não compartilhe este arquivo.\n')
                for key, value in data.items():
                    file.write(f'{key}={json.dumps(value, ensure_ascii=False)}\n')
                file.flush()
                os.fsync(file.fileno())
            temporary.chmod(0o600)
            os.replace(temporary, ENV_PATH)
        finally:
            temporary.unlink(missing_ok=True)


def kick_tokens() -> dict | None:
    data = read()
    if not data.get('KICK_ACCESS_TOKEN'):
        return None
    try:
        metadata = json.loads(data.get('KICK_TOKEN_METADATA', '{}'))
        if not isinstance(metadata, dict): return None
        return {**metadata, 'access_token': data['KICK_ACCESS_TOKEN'],
                'refresh_token': data.get('KICK_REFRESH_TOKEN', ''),
                'client_secret': data.get('KICK_CLIENT_SECRET', '')}
    except ValueError:
        return None


def save_kick_tokens(data: dict) -> None:
    metadata = {k: v for k, v in data.items()
                if k not in ('access_token', 'refresh_token', 'client_secret')}
    update({'KICK_ACCESS_TOKEN': data.get('access_token', ''),
            'KICK_REFRESH_TOKEN': data.get('refresh_token', ''),
            'KICK_CLIENT_SECRET': data.get('client_secret', ''),
            'KICK_TOKEN_METADATA': json.dumps(metadata)})

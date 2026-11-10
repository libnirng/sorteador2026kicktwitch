"""API REST da Twitch: busca avatar por user_id e validação de token.

Requer:
- STATE.bot_twitch_client_id (Client-ID do app em dev.twitch.tv)
- STATE.bot_twitch_oauth (token OAuth — pode ser o mesmo do chat)

Validação de token:
- Usa https://id.twitch.tv/oauth2/validate para verificar token
- Retorna scopes, user_id e client_id do token
- Trata tokens inválidos, expirados ou revogados

Sem credenciais, retorna string vazia. Cache em memória evita repetir requests.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

import httpx

from .state import STATE

log = logging.getLogger('twitch_api')

TWITCH_OAUTH_VALIDATE = 'https://id.twitch.tv/oauth2/validate'
TWITCH_HELIX_BASE = 'https://api.twitch.tv/helix'


@dataclass
class TokenInfo:
    """Informações sobre um token OAuth validado."""
    user_id: str
    client_id: str
    scopes: list[str]
    expires_in: int = 0  # segundos até expirar, 0 = desconhecido
    login: str = ''

    def has_scope(self, scope: str) -> bool:
        """Verifica se o token possui um scope específico."""
        return scope in self.scopes

    @property
    def has_read_chat(self) -> bool:
        return self.has_scope('user:read:chat')

    @property
    def has_write_chat(self) -> bool:
        return self.has_scope('user:write:chat')


class TokenValidationUnavailable(RuntimeError):
    """A validação não respondeu; não significa que o token foi revogado."""


def normalize_token(value: str) -> str:
    token = value.strip()
    if token.lower().startswith('oauth:'):
        token = token[6:].strip()
    elif token.lower().startswith('bearer '):
        token = token[7:].strip()
    return token


async def validate_token(client_id: str, token: str) -> TokenInfo | None:
    """Introspecção independente do Client ID; apenas HTTP 401 invalida o token."""
    token = normalize_token(token)
    if not token:return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(TWITCH_OAUTH_VALIDATE,headers={'Authorization':f'OAuth {token}'})
    except (httpx.HTTPError,ValueError) as error:
        raise TokenValidationUnavailable('Não foi possível acessar a validação da Twitch. Confira internet, proxy ou firewall e tente novamente; o token não foi confirmado como inválido.') from error
    if response.status_code == 401:return None
    if response.status_code != 200:
        raise TokenValidationUnavailable(f'A validação da Twitch retornou HTTP {response.status_code}. Tente novamente; isso não confirma token inválido.')
    try:
        data = response.json()
        return TokenInfo(user_id=str(data.get('user_id','')),client_id=data.get('client_id',''),
                         scopes=data.get('scopes',[]),expires_in=data.get('expires_in',0),login=data.get('login',''))
    except (ValueError,AttributeError) as error:
        raise TokenValidationUnavailable('A validação da Twitch retornou uma resposta inesperada. Tente novamente.') from error


_cache: dict[str, tuple[str, float]] = {}  # user_id -> (avatar_url, ts)
_CACHE_TTL = 3600  # 1 hora
_TWITCH_HELIX_USERS = f'{TWITCH_HELIX_BASE}/users'


async def get_avatar(user_id: str) -> str:
    """Busca URL do avatar de um user_id. Retorna '' se sem credencial ou erro."""
    if not user_id:
        return ''
    if not STATE.bot_twitch_client_id or not STATE.bot_twitch_oauth:
        return ''

    # cache
    now = time.time()
    cached = _cache.get(user_id)
    if cached and (now - cached[1]) < _CACHE_TTL:
        return cached[0]

    token = normalize_token(STATE.bot_twitch_oauth)
    headers = {
        'Authorization': f'Bearer {token}',
        'Client-Id': STATE.bot_twitch_client_id,
    }
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(_TWITCH_HELIX_USERS, params={'id': user_id}, headers=headers)
        if response.status_code != 200:
            return ''
        users = response.json().get('data') or []
        url = users[0].get('profile_image_url', '') if users else ''
        if url:
            _cache[user_id] = (url, now)
        return url or ''
    except (httpx.HTTPError, ValueError):
        return ''


def clear_cache() -> None:
    _cache.clear()

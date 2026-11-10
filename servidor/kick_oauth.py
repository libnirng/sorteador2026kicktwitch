"""Autenticação OAuth 2.1 da Kick com PKCE.

Fluxo:
1. Gerar code_verifier e code_challenge (S256)
2. Gerar URL de autorização
3. Usuário autoriza no navegador
4. Callback com authorization_code + state
5. Trocar code por tokens
6. Refresh automático de tokens
7. Identificação de usuário e canal

Documentação:
https://docs.kick.com/getting-started/generating-tokens-oauth2-flow
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import time
from dataclasses import asdict, dataclass
from typing import Optional

import httpx

from . import secure_storage

logger = logging.getLogger(__name__)

# Endpoints OAuth da Kick
KICK_AUTH_URL = 'https://id.kick.com/oauth/authorize'
KICK_TOKEN_URL = 'https://id.kick.com/oauth/token'
KICK_API_BASE = 'https://api.kick.com'
KICK_INTROSPECT_URL = 'https://id.kick.com/oauth/token/introspect'

# Endpoints públicos da API Kick
KICK_PUBLIC_USERS_URL = 'https://api.kick.com/public/v1/users'
KICK_PUBLIC_CHANNELS_URL = 'https://api.kick.com/public/v1/channels'

# Escopos OAuth (mínimos necessários)
SCOPES = [
    'user:read',
    'channel:read',
    'events:subscribe',
]

# Escopos opcionais (para envio de mensagens)
SCOPES_WITH_CHAT = SCOPES + ['chat:write']

# Escopos obrigatórios para conexão
REQUIRED_SCOPES = ['user:read', 'channel:read', 'events:subscribe']

# Tempo mínimo antes do vencimento para fazer refresh (60 segundos)
REFRESH_BUFFER = 60


@dataclass
class OAuthState:
    """Estado de uma autorização OAuth em andamento."""
    code_verifier: str
    state: str
    scopes: list[str]
    created_at: float
    expires_at: float  # Tempo em que expira (10 minutos)

    @classmethod
    def create(cls, scopes: list[str]) -> 'OAuthState':
        """Cria novo estado OAuth com PKCE."""
        code_verifier = secrets.token_urlsafe(64)[:128]
        state = secrets.token_urlsafe(32)
        now = time.time()
        return cls(
            code_verifier=code_verifier,
            state=state,
            scopes=scopes,
            created_at=now,
            expires_at=now + 600,  # 10 minutos
        )

    def is_valid(self, received_state: str) -> bool:
        """Valida o state recebido e verifica expiração."""
        if time.time() > self.expires_at:
            logger.warning('OAuth state expirou')
            return False
        if received_state != self.state:
            logger.warning(f'OAuth state mismatch: esperado={self.state[:8]}..., recebido={received_state[:8]}...')
            return False
        return True


@dataclass
class UserInfo:
    """Informações do usuário autenticado."""
    user_id: str
    username: str
    email: str = ''
    channels: list = None

    def __post_init__(self):
        if self.channels is None:
            self.channels = []


@dataclass
class ChannelInfo:
    """Informações do canal do usuário."""
    broadcaster_user_id: str
    slug: str
    name: str = ''
    is_live: bool = False


@dataclass
class TokenIntrospection:
    """Resultado da introspecção de token.

    Resposta oficial:
    {
        "data": {
            "active": true,
            "client_id": "string",
            "token_type": "user" | "app",
            "scope": "user:read channel:read",
            "exp": 1771046347
        }
    }
    """
    active: bool
    client_id: str
    token_type: str  # "user" ou "app"
    scope: str
    exp: int

    @property
    def is_user_token(self) -> bool:
        """Verdadeiro se for User Access Token."""
        return self.token_type == 'user'


class KickOAuth:
    """Gerenciador de autenticação OAuth 2.1 da Kick."""

    def __init__(self, client_id: str, redirect_uri: str, client_secret: str = ''):
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.client_secret = client_secret

        # Estado de autorizações em andamento
        self._pending_authorizations: dict[str, OAuthState] = {}

        # Tokens após autorização
        self._access_token: str = ''
        self._refresh_token: str = ''
        self._token_type: str = 'Bearer'
        self._expires_at: float = 0.0
        self._granted_scopes: list[str] = []

        # Informações do usuário
        self._user_id: str = ''
        self._username: str = ''
        self._email: str = ''

        # Informações do canal
        self._channel_info: Optional[ChannelInfo] = None

        # Lock para evitar refresh simultâneos
        self._refresh_lock: asyncio.Lock = asyncio.Lock()

        # Storage seguro
        self._storage = secure_storage.get_storage()

    @staticmethod
    def generate_code_challenge(verifier: str) -> str:
        """Gera code_challenge a partir do code_verifier usando S256."""
        digest = hashlib.sha256(verifier.encode('ascii')).digest()
        import base64
        challenge = base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')
        return challenge

    @staticmethod
    def generate_authorization_url(
        client_id: str,
        redirect_uri: str,
        scopes: list[str],
        state: str,
        code_challenge: str,
    ) -> str:
        """Gera URL de autorização OAuth."""
        import urllib.parse

        params = {
            'client_id': client_id,
            **({'redirect': '127.0.0.1'} if urllib.parse.urlsplit(redirect_uri).hostname == '127.0.0.1' else {}),
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': ' '.join(scopes),
            'state': state,
            'code_challenge': code_challenge,
            'code_challenge_method': 'S256',
        }
        query = urllib.parse.urlencode(params)
        return f'{KICK_AUTH_URL}?{query}'

    def start_authorization(self, include_chat: bool = False) -> str:
        """Inicia fluxo OAuth e retorna URL de autorização."""
        if not self.client_id:
            raise ValueError('client_id não configurado')
        if not self.redirect_uri:
            raise ValueError('Redirect URI não configurada. Copie a URI cadastrada no aplicativo da Kick.')
        if not self.client_secret:
            raise ValueError('Client Secret não configurado. Copie o segredo do mesmo aplicativo do Client ID.')
        from urllib.parse import urlsplit
        redirect = urlsplit(self.redirect_uri)
        if redirect.scheme not in ('http', 'https') or not redirect.hostname or redirect.fragment:
            raise ValueError('Redirect URI inválida. Use uma URL completa, igual à cadastrada na Kick.')

        scopes = SCOPES_WITH_CHAT if include_chat else SCOPES

        # Cria estado
        state_obj = OAuthState.create(scopes)
        self._pending_authorizations[state_obj.state] = state_obj

        # Gera challenge
        code_challenge = self.generate_code_challenge(state_obj.code_verifier)

        # Gera URL
        url = self.generate_authorization_url(
            client_id=self.client_id,
            redirect_uri=self.redirect_uri,
            scopes=scopes,
            state=state_obj.state,
            code_challenge=code_challenge,
        )

        logger.info(f'OAuth: URL gerada para escopos: {scopes}')
        return url

    def validate_callback(self, code: str, state: str) -> tuple[bool, str]:
        """Valida callback OAuth e retorna code_verifier para troca de tokens."""
        if not state:
            return False, 'State ausente'

        # Busca estado pendente
        state_obj = self._pending_authorizations.get(state)
        if not state_obj:
            return False, f'State inválido: {state[:8]}...'

        # Valida state e expiração
        if not state_obj.is_valid(state):
            del self._pending_authorizations[state]
            return False, 'State expirado ou inválido'

        # Remove state usado (impede reutilização)
        del self._pending_authorizations[state]

        logger.info(f'OAuth: callback válido para escopos: {state_obj.scopes}')
        return True, state_obj.code_verifier

    def has_valid_token(self) -> bool:
        """Verifica se tem token de acesso válido."""
        if not self._access_token:
            return False
        # Considera válido se ainda faltam 60 segundos
        return time.time() < (self._expires_at - REFRESH_BUFFER)

    def get_access_token(self) -> str:
        """Retorna token de acesso (vazio se não disponível)."""
        return self._access_token

    def get_user_info(self) -> tuple[str, str]:
        """Retorna (user_id, username) do usuário autenticado."""
        return self._user_id, self._username

    def get_channel_info(self) -> Optional[ChannelInfo]:
        """Retorna informações do canal."""
        return self._channel_info

    def get_granted_scopes(self) -> list[str]:
        """Retorna escopos concedidos."""
        return self._granted_scopes.copy()

    def has_required_scopes(self) -> bool:
        """Verifica se tem todos os escopos obrigatórios (inclui events:subscribe)."""
        return all(s in self._granted_scopes for s in REQUIRED_SCOPES)

    def has_chat_scopes(self) -> bool:
        """Verifica escopos mínimos para chat (user:read + channel:read)."""
        return 'user:read' in self._granted_scopes and 'channel:read' in self._granted_scopes

    def has_events_subscribe(self) -> bool:
        """Verifica se tem o escopo events:subscribe (necessário para webhooks)."""
        return 'events:subscribe' in self._granted_scopes

    def has_channel_read(self) -> bool:
        """Verifica se tem o escopo channel:read."""
        return 'channel:read' in self._granted_scopes

    def has_user_read(self) -> bool:
        """Verifica se tem o escopo user:read."""
        return 'user:read' in self._granted_scopes

    def has_chat_write(self) -> bool:
        """Verifica se tem o escopo chat:write (opcional, para envio de mensagens)."""
        return 'chat:write' in self._granted_scopes

    def is_user_token(self) -> bool:
        """Verifica se é User Access Token (tem user_id)."""
        return bool(self._user_id)

    async def exchange_code_for_tokens(
        self,
        code: str,
        code_verifier: str,
    ) -> tuple[bool, str]:
        """Troca authorization_code por access_token e refresh_token."""
        if not self.client_id:
            return False, 'client_id não configurado'

        if not code:
            return False, 'code é obrigatório'

        if not code_verifier:
            return False, 'code_verifier é obrigatório'

        redirect_uri = self.redirect_uri or ''

        data = {
            'grant_type': 'authorization_code',
            'client_id': self.client_id,
            'code': code,
            'redirect_uri': redirect_uri,
            'code_verifier': code_verifier,
        }

        if self.client_secret:
            data['client_secret'] = self.client_secret

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    KICK_TOKEN_URL,
                    data=data,
                    headers={'Content-Type': 'application/x-www-form-urlencoded'},
                )

            if response.status_code != 200:
                try:
                    error_data = response.json()
                    error_msg = error_data.get('error_description') or error_data.get('error', response.text)
                except Exception:
                    error_msg = response.text[:200]

                logger.error(f'OAuth: troca de tokens falhou ({response.status_code}): {error_msg}')
                return False, f'Erro {response.status_code}: {error_msg}'

            # Parse resposta
            token_data = response.json()

            if 'access_token' not in token_data:
                return False, 'Resposta inválida: access_token ausente'

            # Extrai dados
            access_token = token_data.get('access_token', '')
            refresh_token = token_data.get('refresh_token', '')
            token_type = token_data.get('token_type', 'Bearer')
            expires_in = int(token_data.get('expires_in', 0))
            scope = token_data.get('scope', '')

            # Parse escopos
            granted_scopes = scope.split() if isinstance(scope, str) else list(scope or [])

            # Busca informações do usuário e canal
            user_info = await self._fetch_user_info(access_token)
            channel_info = await self._fetch_channel_info(access_token)

            # Atualiza tokens em memória
            self._set_tokens_internal(
                access_token=access_token,
                refresh_token=refresh_token,
                token_type=token_type,
                expires_in=expires_in,
                user_id=user_info.user_id,
                username=user_info.username,
                granted_scopes=granted_scopes,
                user_email=user_info.email,
            )

            # Atualiza info do canal
            self._channel_info = channel_info

            # Salva de forma segura
            self._save_tokens()

            channel_slug = channel_info.slug if channel_info else 'N/A'
            logger.info(f'OAuth: tokens trocados com sucesso (user={user_info.username}, channel={channel_slug})')
            return True, ''

        except httpx.TimeoutException:
            logger.error('OAuth: timeout ao trocar tokens')
            return False, 'Timeout ao trocar tokens'
        except httpx.ConnectError as e:
            logger.error(f'OAuth: erro de conexão: {e!r}')
            return False, f'Erro de conexão: {e!r}'
        except Exception as e:
            logger.exception('OAuth: erro inesperado ao trocar tokens')
            return False, f'Erro inesperado: {e!r}'

    async def refresh_tokens(self) -> tuple[bool, str]:
        """Renova tokens usando refresh_token."""
        async with self._refresh_lock:
            return await self._refresh_tokens_internal()

    async def _refresh_tokens_internal(self) -> tuple[bool, str]:
        """Renova tokens internamente (já dentro do lock)."""
        if not self._refresh_token:
            return False, 'Refresh token não disponível'

        if not self.client_id:
            return False, 'client_id não configurado'

        data = {
            'grant_type': 'refresh_token',
            'client_id': self.client_id,
            'refresh_token': self._refresh_token,
        }

        if self.client_secret:
            data['client_secret'] = self.client_secret

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    KICK_TOKEN_URL,
                    data=data,
                    headers={'Content-Type': 'application/x-www-form-urlencoded'},
                )

            if response.status_code != 200:
                try:
                    error_data = response.json()
                    error_msg = error_data.get('error_description') or error_data.get('error', response.text)
                except Exception:
                    error_msg = response.text[:200]

                if 'invalid_grant' in error_msg.lower() or 'revoked' in error_msg.lower():
                    logger.warning('OAuth: refresh token revogado ou expirado')
                    self._clear_tokens_internal()
                    return False, 'Token expirado. Faça login novamente.'

                logger.error(f'OAuth: refresh falhou ({response.status_code}): {error_msg}')
                return False, f'Erro {response.status_code}: {error_msg}'

            token_data = response.json()

            if 'access_token' not in token_data:
                return False, 'Resposta inválida: access_token ausente'

            access_token = token_data.get('access_token', '')
            refresh_token = token_data.get('refresh_token', '') or self._refresh_token
            token_type = token_data.get('token_type', 'Bearer')
            expires_in = int(token_data.get('expires_in', 0))
            scope = token_data.get('scope', '')
            granted_scopes = scope.split() if scope else self._granted_scopes

            self._set_tokens_internal(
                access_token=access_token,
                refresh_token=refresh_token,
                token_type=token_type,
                expires_in=expires_in,
                user_id=self._user_id,
                username=self._username,
                granted_scopes=granted_scopes,
                user_email=self._email,
            )

            self._save_tokens()

            logger.info('OAuth: tokens renovados com sucesso')
            return True, ''

        except httpx.TimeoutException:
            logger.error('OAuth: timeout ao renovar tokens')
            return False, 'Timeout ao renovar tokens'
        except httpx.ConnectError as e:
            logger.error(f'OAuth: erro de conexão ao renovar: {e!r}')
            return False, f'Erro de conexão: {e!r}'
        except Exception as e:
            logger.exception('OAuth: erro inesperado ao renovar tokens')
            return False, f'Erro inesperado: {e!r}'

    async def ensure_valid_token(self) -> tuple[bool, str]:
        """Garante token válido, renovando se necessário."""
        if self.has_valid_token():
            return True, self._access_token

        if self._refresh_token:
            success, error = await self.refresh_tokens()
            if success:
                return True, self._access_token
            return False, error

        return False, 'Token expirado e sem refresh token'

    async def introspect_token(self) -> Optional[TokenIntrospection]:
        """Valida token usando introspecção oficial.

        Endpoint: POST https://id.kick.com/oauth/token/introspect
        Header: Authorization: Bearer <access_token>

        Returns:
            TokenIntrospection se o token for válido, None se inválido
        """
        if not self._access_token:
            return None

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    KICK_INTROSPECT_URL,
                    headers={
                        'Authorization': f'Bearer {self._access_token}',
                    },
                )

            if response.status_code != 200:
                logger.warning(f'OAuth: introspecção falhou ({response.status_code}): {response.text[:100]}')
                return None

            result = response.json()

            # Resposta está em {data: {...}}
            data = result.get('data', {})
            if not data:
                logger.warning('OAuth: introspecção sem data')
                return None

            # Se active=false, token é inválido
            if not data.get('active', False):
                logger.info('OAuth: token não está ativo (introspecção)')
                return None

            return TokenIntrospection(
                active=True,
                client_id=data.get('client_id', ''),
                token_type=data.get('token_type', ''),  # "user" ou "app"
                scope=data.get('scope', ''),
                exp=int(data.get('exp', 0)),
            )

        except Exception as e:
            logger.warning(f'OAuth: erro na introspecção: {e!r}')
            return None

    async def _fetch_user_info(self, access_token: str) -> UserInfo:
        """Busca informações do usuário autenticado via API pública.

        Endpoint: GET https://api.kick.com/public/v1/users
        Sem parâmetros = retorna dados do usuário autenticado.

        Resposta:
        {
            "data": [
                {
                    "email": "string",
                    "name": "string",
                    "profile_picture": "string",
                    "user_id": 0
                }
            ]
        }
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    KICK_PUBLIC_USERS_URL,  # Sem parâmetros = usuário autenticado
                    headers={
                        'Authorization': f'Bearer {access_token}',
                        'Accept': 'application/json',
                    },
                )

                if response.status_code == 200:
                    result = response.json()
                    data = result.get('data', [])
                    if data:
                        user = data[0]
                        return UserInfo(
                            user_id=str(user.get('user_id', '')),
                            username=user.get('name', ''),
                            email=user.get('email', ''),
                        )

            # Se não conseguiu, retorna info mínima
            return UserInfo(user_id='', username='')

        except Exception as e:
            logger.warning(f'OAuth: erro ao buscar user info: {e!r}')
            return UserInfo(user_id='', username='')

    async def _fetch_channel_info(self, access_token: str) -> Optional[ChannelInfo]:
        """Busca informações do canal do usuário autenticado.

        Endpoint: GET https://api.kick.com/public/v1/channels
        Sem parâmetros = retorna canal do usuário autenticado.

        Resposta:
        {
            "data": [
                {
                    "broadcaster_user_id": 0,
                    "slug": "string",
                    "channel_description": "string",
                    "stream": {
                        "is_live": false,
                        ...
                    },
                    ...
                }
            ]
        }
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    KICK_PUBLIC_CHANNELS_URL,  # Sem parâmetros = canal do usuário autenticado
                    headers={
                        'Authorization': f'Bearer {access_token}',
                        'Accept': 'application/json',
                    },
                )

                if response.status_code == 200:
                    result = response.json()
                    data = result.get('data', [])
                    if data:
                        channel = data[0]
                        stream_data = channel.get('stream', {})
                        return ChannelInfo(
                            broadcaster_user_id=str(channel.get('broadcaster_user_id', '')),
                            slug=channel.get('slug', ''),
                            name=channel.get('slug', ''),  # slug é o nome do canal
                            is_live=stream_data.get('is_live', False),
                        )

            return None

        except Exception as e:
            logger.warning(f'OAuth: erro ao buscar channel info: {e!r}')
            return None

    async def validate_connection(self) -> tuple[bool, str]:
        """Valida a conexão verificando token e permissões.

        Returns:
            (success, error_message)
        """
        # Verifica se tem token
        if not self._access_token:
            return False, 'Credenciais ausentes'

        # Tenta introspecção para verificar token
        intro = await self.introspect_token()
        if intro is None:
            return False, 'Token inválido, expirado ou API indisponível'

        # Verifica se é User Token via token_type
        if not intro.is_user_token:
            return False, 'App Token detectado (requer User Token)'

        # Verifica escopos
        granted = intro.scope.split() if intro.scope else self._granted_scopes
        missing = [s for s in REQUIRED_SCOPES if s not in granted]
        if missing:
            return False, f'Escopos ausentes: {missing}'

        return True, ''

    def _set_tokens_internal(
        self,
        access_token: str,
        refresh_token: str,
        token_type: str,
        expires_in: int,
        user_id: str,
        username: str,
        granted_scopes: list[str],
        user_email: str = '',
    ) -> None:
        """Define tokens em memória."""
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._token_type = token_type
        self._expires_at = time.time() + expires_in if expires_in > 0 else float('inf')
        self._user_id = user_id
        self._username = username
        self._email = user_email
        self._granted_scopes = granted_scopes

    def _save_tokens(self) -> bool:
        """Salva tokens de forma segura."""
        from . import env_config
        env_config.save_kick_tokens({'access_token': self._access_token,
            'refresh_token': self._refresh_token, 'token_type': self._token_type,
            'client_id': self.client_id,
            'user_id': self._user_id, 'username': self._username,
            'client_secret': self.client_secret, 'expires_at': self._expires_at,
            'granted_scopes': self._granted_scopes,
            'channel_info': asdict(self._channel_info) if self._channel_info else None})
        self._storage.save_token(
            access_token=self._access_token,
            refresh_token=self._refresh_token,
            token_type=self._token_type,
            expires_in=int(self._expires_at - time.time()) if self._expires_at != float('inf') else 0,
            user_id=self._user_id,
            username=self._username,
            client_secret=self.client_secret,
            metadata={'expires_at': self._expires_at, 'granted_scopes': self._granted_scopes,
                      'channel_info': asdict(self._channel_info) if self._channel_info else None},
        )
        return True

    def load_saved_tokens(self) -> bool:
        """Carrega tokens salvos anteriormente."""
        from . import env_config
        data = env_config.kick_tokens() or self._storage.load_token()
        if not data:
            return False

        if not data.get('access_token'):
            return False
        if data.get('client_id') and data['client_id'] != self.client_id:
            return False

        self._access_token = data.get('access_token', '')
        self._refresh_token = data.get('refresh_token', '')
        self._token_type = data.get('token_type', 'Bearer')
        self._user_id = data.get('user_id', '')
        self._username = data.get('username', '')

        if data.get('client_secret') and not self.client_secret:
            self.client_secret = data['client_secret']

        # Expiração absoluta: reiniciar o programa não prolonga a validade do token.
        self._expires_at = float(data.get('expires_at', 0))
        self._granted_scopes = data.get('granted_scopes', [])
        channel = data.get('channel_info')
        if channel:
            self._channel_info = ChannelInfo(**channel)

        logger.info(f'OAuth: tokens carregados (user={self._username})')
        return True

    def _clear_tokens_internal(self) -> None:
        """Limpa tokens em memória."""
        self._access_token = ''
        self._refresh_token = ''
        self._token_type = 'Bearer'
        self._expires_at = 0.0
        self._user_id = ''
        self._username = ''
        self._email = ''
        self._granted_scopes = []
        self._channel_info = None

    def clear_tokens(self) -> None:
        """Limpa todos os tokens (logout)."""
        self._clear_tokens_internal()
        self._storage.delete_token()
        from . import env_config
        env_config.update({'KICK_ACCESS_TOKEN': '', 'KICK_REFRESH_TOKEN': '', 'KICK_TOKEN_METADATA': '{}'})
        logger.info('OAuth: tokens limpos')

    def get_config_dict(self) -> dict:
        """Retorna configuração para persistência (sem segredos)."""
        channel = self._channel_info
        return {
            'client_id': self.client_id,
            'redirect_uri': self.redirect_uri,
            'has_secret': bool(self.client_secret),
            'is_authorized': self.has_valid_token(),
            'is_user_token': self._user_id != '',  # Tem user_id = User Token
            'has_required_scopes': self.has_required_scopes(),
            'username': self._username,
            'user_id': self._user_id,
            'channel_slug': channel.slug if channel else '',
            'broadcaster_user_id': channel.broadcaster_user_id if channel else '',
            'granted_scopes': self._granted_scopes,
            'expires_at': self._expires_at if self._expires_at < float('inf') else 0,
        }

    def get_full_status(self) -> dict:
        """Retorna status completo da autenticação.

        Nunca expõe credenciais confidenciais.

        authenticated = token existe + válido + é User Token (tem user_id)
        """
        channel = self._channel_info
        has_user_id = bool(self._user_id)
        token_ok = self.has_valid_token()
        return {
            # authenticated = token existe E válido E é User Token
            'authenticated': bool(self._access_token) and token_ok and has_user_id,
            'token_valid': token_ok,
            'is_user_token': has_user_id,
            'has_required_scopes': self.has_required_scopes(),
            'username': self._username,
            'user_id': self._user_id,
            'email': '',  # Nunca exposto
            'channel_slug': channel.slug if channel else '',
            'broadcaster_user_id': channel.broadcaster_user_id if channel else '',
            'granted_scopes': self._granted_scopes,
            'missing_scopes': [s for s in REQUIRED_SCOPES if s not in self._granted_scopes],
            'expires_at': self._expires_at if self._expires_at < float('inf') else 0,
            'expires_in_seconds': max(0, int(self._expires_at - time.time())) if self._expires_at != float('inf') else -1,
        }

    def load_from_config(self, config: dict) -> None:
        """Carrega configuração (sem segredos)."""
        self.client_id = config.get('client_id', '')
        self.redirect_uri = config.get('redirect_uri', '')


# Instância global (inicializada em app.py)
oauth: Optional['KickOAuth'] = None


def get_oauth() -> 'KickOAuth':
    """Retorna instância global do OAuth."""
    global oauth
    if oauth is None:
        raise RuntimeError('KickOAuth não inicializado. Chame setup_oauth() primeiro.')
    return oauth


def setup_oauth(
    client_id: str = '',
    redirect_uri: str = '',
    client_secret: str = '',
) -> 'KickOAuth':
    """Inicializa instância global do OAuth."""
    global oauth
    from . import env_config
    saved = env_config.read()
    oauth = KickOAuth(
        client_id=client_id,
        redirect_uri=redirect_uri,
        client_secret=client_secret or (saved.get('KICK_CLIENT_SECRET', '') if saved.get('KICK_CLIENT_ID') == client_id else ''),
    )
    # Tenta carregar tokens salvos
    oauth.load_saved_tokens()
    return oauth

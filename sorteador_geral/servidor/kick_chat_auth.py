"""Gerenciador de conexão OAuth + Chat do Kick.

Este módulo integra o OAuth existente com a estrutura de chat:
- Verifica status de autenticação OAuth
- Identifica canal e valida permissões
- Prepara para receber eventos de webhook futuramente
- Mantém interface pública do ChatManager

Arquitetura:
- KickOAuth (kick_oauth.py): tokens, refresh, introspecção
- KickAuthConnection (este): validação de conexão, status detalhado
- KickChat (kick_chat.py): comunicação real do chat

Status de conexão (do mais grave ao menos):
1. oauth_not_configured - OAuth não foi configurado
2. oauth_no_token - Token não disponível
3. oauth_expired - Token expirado
4. oauth_invalid - Token inválido (revogado, API indisponível)
5. app_token - App Token detectado (requer User Token)
6. missing_scopes - Escopos insuficientes
7. channel_not_found - Canal não identificado
8. events_subscribe_missing - Falta events:subscribe (webhook)
9. ready - Pronto (OAuth válido, escopos OK, canal identificado)
10. connected - Chat operacional (futuro)
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class KickAuthStatus:
    """Status detalhado da conexão OAuth do Kick."""
    # Status geral
    status: str  # Um dos valores acima
    is_authenticated: bool = False  # Token válido + User Token
    is_channel_identified: bool = False
    is_ready: bool = False  # Pode tentar conectar

    # Token info
    token_valid: bool = False
    is_user_token: bool = False
    expires_in_seconds: int = -1

    # Escopos
    has_required_scopes: bool = False
    has_events_subscribe: bool = False
    missing_scopes: list = None

    # Canal
    user_id: str = ''
    username: str = ''
    channel_slug: str = ''
    broadcaster_user_id: str = ''

    # Mensagem de erro/detalhe
    message: str = ''

    def __post_init__(self):
        if self.missing_scopes is None:
            self.missing_scopes = []


class KickAuthConnection:
    """Gerencia autenticação e preparação para conexão do chat Kick.

    Não implementa a conexão real (isso é KickChat).
    Valida OAuth e fornece status detalhado.
    """

    def __init__(self):
        self._oauth = None  # Referência ao KickOAuth (definido em setup)

    def set_oauth(self, oauth) -> None:
        """Define a instância do OAuth (chamado por setup)."""
        self._oauth = oauth

    def get_status(self) -> KickAuthStatus:
        """Retorna status detalhado da conexão.

        Este método é síncrono e não faz chamadas de API.
        Para verificação em tempo real, use validate_oauth().
        """
        status = KickAuthStatus(status='oauth_not_configured', message='OAuth não configurado')

        if self._oauth is None:
            return status

        oauth = self._oauth

        # 1. Verifica se tem token armazenado
        if not oauth._access_token:
            status.status = 'oauth_no_token'
            status.message = 'Token não disponível. Faça login primeiro.'
            return status

        # 2. Verifica se token expirou
        if not oauth.has_valid_token():
            status.status = 'oauth_expired'
            status.message = 'Token expirado. Tente renovar.'
            status.token_valid = False
            status.is_authenticated = False
            return status

        status.token_valid = True

        # 3. Verifica se é User Token
        if not oauth.is_user_token():
            status.status = 'app_token'
            status.message = 'App Token detectado. É necessário User Token para chat.'
            status.is_user_token = False
            status.is_authenticated = False
            return status

        status.is_user_token = True

        # 4. Verifica escopos mínimos para chat (user:read + channel:read)
        if not oauth.has_chat_scopes():
            required = ['user:read', 'channel:read']
            status.missing_scopes = [s for s in required if s not in oauth._granted_scopes]
            status.status = 'missing_scopes'
            status.message = f'Escopos ausentes: {status.missing_scopes}'
            status.has_required_scopes = False
            status.is_authenticated = False
            return status

        status.has_required_scopes = True
        status.missing_scopes = []

        # 5. Verifica events:subscribe (necessário para webhooks, opcional para chat)
        if not oauth.has_events_subscribe():
            status.status = 'events_subscribe_missing'
            status.message = 'Escopo events:subscribe ausente. Webhooks não funcionarão.'
            status.has_events_subscribe = False
            # Canal identificado = pode conectar, só webhooks não
        else:
            status.has_events_subscribe = True

        # 6. Informações do usuário e canal
        status.user_id = oauth._user_id
        status.username = oauth._username
        status.is_authenticated = True

        channel = oauth.get_channel_info()
        if channel:
            status.channel_slug = channel.slug
            status.broadcaster_user_id = channel.broadcaster_user_id
            status.is_channel_identified = True
        else:
            status.status = 'channel_not_found'
            status.message = 'Canal não identificado. Verifique as permissões.'
            status.is_channel_identified = False

        # 7. Status final
        if status.is_channel_identified:
            if status.has_events_subscribe:
                status.status = 'ready'
                status.message = 'Pronto para conectar ao chat.'
            else:
                status.status = 'ready_no_events'
                status.message = 'Pronto para conectar (sem webhooks).'
            status.is_ready = True

        status.expires_in_seconds = max(0, int(oauth._expires_at - __import__('time').time())) if oauth._expires_at != float('inf') else -1

        return status

    async def validate_oauth(self) -> tuple[bool, str]:
        """Valida OAuth via introspecção (chamada de API).

        Use este método para verificação em tempo real.

        Returns:
            (success, error_message)
        """
        if self._oauth is None:
            return False, 'OAuth não configurado'

        return await self._oauth.validate_connection()

    def can_connect(self) -> bool:
        """Verifica se pode tentar conectar ao chat.

        Returns:
            True se OAuth está válido e canal identificado.
        """
        status = self.get_status()
        return status.is_ready and status.is_channel_identified

    def get_channel_slug(self) -> str:
        """Retorna o slug do canal identificado, ou vazio."""
        status = self.get_status()
        return status.channel_slug

    def get_required_channel(self) -> tuple[bool, str]:
        """Retorna o canal que o usuário pretende usar.

        Returns:
            (has_channel, channel_slug)
        """
        status = self.get_status()
        if status.is_channel_identified:
            return True, status.channel_slug
        return False, ''


# Instância global
_kick_auth: Optional[KickAuthConnection] = None


def get_kick_auth() -> KickAuthConnection:
    """Retorna instância global."""
    global _kick_auth
    if _kick_auth is None:
        _kick_auth = KickAuthConnection()
    return _kick_auth


def setup_kick_auth(oauth) -> KickAuthConnection:
    """Configura e retorna instância global."""
    auth = get_kick_auth()
    auth.set_oauth(oauth)
    return auth

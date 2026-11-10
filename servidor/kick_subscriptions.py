"""Gerenciamento de assinaturas de eventos da Kick API.

Referência:
https://docs.kick.com/events/subscribe-to-events
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from . import kick_oauth

logger = logging.getLogger(__name__)

KICK_API_BASE = 'https://api.kick.com/public/v1'


@dataclass
class KickSubscription:
    """Uma assinatura de evento."""
    id: str
    name: str
    version: int
    status: str
    created_at: str
    updated_at: str
    webhook_url: str = ''


@dataclass
class SubscriptionResult:
    """Resultado de uma operação de assinatura."""
    success: bool
    subscription: KickSubscription | None = None
    error: str = ''
    message: str = ''


@dataclass
class SubscriptionListResult:
    """Resultado da listagem de assinaturas."""
    success: bool
    subscriptions: list[KickSubscription] = None
    error: str = ''
    message: str = ''

    def __post_init__(self):
        if self.subscriptions is None:
            self.subscriptions = []


class KickSubscriptions:
    """Gerencia assinaturas de eventos da Kick."""

    async def list(self, broadcaster_id: str = '') -> SubscriptionListResult:
        """Lista assinaturas de eventos.

        Args:
            broadcaster_id: Filtrar por broadcaster (opcional)

        Returns:
            SubscriptionListResult com sucesso ou erro detalhado
        """
        oauth = kick_oauth.get_oauth()
        valid, token = await oauth.ensure_valid_token()
        if not valid:
            return SubscriptionListResult(
                success=False,
                error='oauth_not_configured',
                message='OAuth não configurado ou token inválido',
            )

        headers = {
            'Authorization': f'Bearer {token}',
            'Client-Id': oauth.client_id,
        }

        params = {}
        if broadcaster_id:
            params['broadcaster_user_id'] = broadcaster_id

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f'{KICK_API_BASE}/events/subscriptions',
                    headers=headers,
                    params=params,
                )

            if r.status_code == 200:
                data = r.json()
                subscriptions = [
                    KickSubscription(
                        id=s.get('id', ''),
                        name=s.get('event', s.get('name', '')),
                        version=s.get('version', 1),
                        status=s.get('status', 'enabled'),
                        created_at=s.get('created_at', ''),
                        updated_at=s.get('updated_at', ''),
                        webhook_url=s.get('webhook_url', ''),
                    )
                    for s in data.get('data', [])
                ]
                return SubscriptionListResult(
                    success=True,
                    subscriptions=subscriptions,
                    message=f'{len(subscriptions)} assinatura(s) encontrada(s)',
                )

            # Diferencia erros HTTP
            if r.status_code == 401:
                return SubscriptionListResult(
                    success=False,
                    error='unauthorized',
                    message='Token inválido ou expirado',
                )

            if r.status_code == 403:
                return SubscriptionListResult(
                    success=False,
                    error='forbidden',
                    message='Sem permissão para listar assinaturas',
                )

            logger.warning(f'Falha ao listar assinaturas: {r.status_code} {r.text[:200]}')
            return SubscriptionListResult(
                success=False,
                error='api_error',
                message=f'Erro API: {r.status_code}',
            )

        except httpx.ConnectError:
            logger.error('Erro de conexão com API Kick')
            return SubscriptionListResult(
                success=False,
                error='connection_error',
                message='Erro de conexão com a API Kick',
            )

        except Exception as e:
            logger.error(f'Erro ao listar assinaturas: {e!r}')
            return SubscriptionListResult(
                success=False,
                error='unknown_error',
                message=str(e),
            )

    async def create(
        self,
        webhook_url: str,
        events: list[dict[str, Any]] | None = None,
        broadcaster_id: str = '',
    ) -> SubscriptionResult:
        """Cria assinatura de eventos via webhook.

        Args:
            webhook_url: URL do webhook (deve ser HTTPS)
            events: Lista de eventos (padrão: chat.message.sent v1)
            broadcaster_id: ID do broadcaster (opcional, ignorado com User Token)

        Returns:
            SubscriptionResult com sucesso ou erro
        """
        oauth = kick_oauth.get_oauth()
        valid, token = await oauth.ensure_valid_token()
        if not valid:
            return SubscriptionResult(
                success=False,
                error='oauth_not_configured',
                message='OAuth não configurado ou token inválido',
            )

        # Verifica escopo
        if 'events:subscribe' not in oauth._granted_scopes:
            return SubscriptionResult(
                success=False,
                error='missing_scope',
                message='Token sem escopo events:subscribe',
            )

        headers = {
            'Authorization': f'Bearer {token}',
            'Client-Id': oauth.client_id,
            'Content-Type': 'application/json',
        }

        # Corpo padrão
        if events is None:
            events = [{'name': 'chat.message.sent', 'version': 1}]

        body: dict[str, Any] = {
            'events': events,
            'method': 'webhook',
        }

        # broadcaster_user_id só é obrigatório com App Token
        if broadcaster_id:
            body['broadcaster_user_id'] = int(broadcaster_id)

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f'{KICK_API_BASE}/events/subscriptions',
                    headers=headers,
                    json=body,
                )

            if r.status_code == 200:
                data = r.json()
                # Verifica se há erro na resposta
                if data.get('error'):
                    return SubscriptionResult(
                        success=False,
                        error=data.get('error', 'unknown'),
                        message=data.get('message', 'Erro desconhecido'),
                    )

                entries = data.get('data') or []
                if isinstance(entries, dict):
                    entries = [entries]
                sub_data = next((entry for entry in entries if entry.get('name', entry.get('event')) == 'chat.message.sent'), entries[0] if entries else {})
                sub_id = sub_data.get('subscription_id', sub_data.get('id', ''))
                if sub_data.get('error') or not sub_id:
                    return SubscriptionResult(success=False, error='subscription_failed',
                        message=sub_data.get('error') or 'A Kick não confirmou uma assinatura')
                return SubscriptionResult(
                    success=True,
                    subscription=KickSubscription(
                        id=sub_id, name=sub_data.get('name', sub_data.get('event', '')),
                        version=sub_data.get('version', 1), status='enabled',
                        created_at=sub_data.get('created_at', ''), updated_at=sub_data.get('updated_at', ''),
                        webhook_url=webhook_url),
                    message='Assinatura criada com sucesso',
                )

            # Erros comuns
            if r.status_code == 400:
                try:
                    err_data = r.json()
                    return SubscriptionResult(
                        success=False,
                        error=err_data.get('error', 'bad_request'),
                        message=err_data.get('message', 'Requisição inválida'),
                    )
                except Exception:
                    return SubscriptionResult(
                        success=False,
                        error='bad_request',
                        message=f'Status {r.status_code}',
                    )

            if r.status_code == 401:
                return SubscriptionResult(
                    success=False,
                    error='unauthorized',
                    message='Token inválido ou expirado',
                )

            if r.status_code == 403:
                return SubscriptionResult(
                    success=False,
                    error='forbidden',
                    message='Sem permissão para criar assinatura',
                )

            logger.warning(f'Falha ao criar assinatura: {r.status_code} {r.text[:200]}')
            return SubscriptionResult(
                success=False,
                error='api_error',
                message=f'Erro API: {r.status_code}',
            )

        except Exception as e:
            logger.error(f'Erro ao criar assinatura: {e!r}')
            return SubscriptionResult(
                success=False,
                error='network_error',
                message=str(e),
            )

    async def delete(self, subscription_id: str) -> SubscriptionResult:
        """Cancela uma assinatura.

        Args:
            subscription_id: ID da assinatura a cancelar

        Returns:
            SubscriptionResult com sucesso ou erro
        """
        oauth = kick_oauth.get_oauth()
        valid, token = await oauth.ensure_valid_token()
        if not valid:
            return SubscriptionResult(
                success=False,
                error='oauth_not_configured',
                message='OAuth não configurado',
            )

        headers = {
            'Authorization': f'Bearer {token}',
            'Client-Id': oauth.client_id,
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.delete(
                    f'{KICK_API_BASE}/events/subscriptions',
                    params={'id': subscription_id}, headers=headers,
                )

            if r.status_code == 204:
                return SubscriptionResult(
                    success=True,
                    message='Assinatura cancelada',
                )

            if r.status_code == 404:
                return SubscriptionResult(
                    success=False,
                    error='not_found',
                    message='Assinatura não encontrada',
                )

            if r.status_code == 401:
                return SubscriptionResult(
                    success=False,
                    error='unauthorized',
                    message='Token inválido',
                )

            logger.warning(f'Falha ao cancelar assinatura: {r.status_code} {r.text[:200]}')
            return SubscriptionResult(
                success=False,
                error='api_error',
                message=f'Erro API: {r.status_code}',
            )

        except Exception as e:
            logger.error(f'Erro ao cancelar assinatura: {e!r}')
            return SubscriptionResult(
                success=False,
                error='network_error',
                message=str(e),
            )

    async def find_chat_message_subscription(
        self,
        webhook_url: str = '',
    ) -> KickSubscription | None:
        """Encontra assinatura de chat.message.sent.

        Args:
            webhook_url: Filtrar por URL do webhook (opcional)

        Returns:
            Assinatura se encontrada, None caso contrário
        """
        result = await self.list()

        # Se a listagem falhou, retorna None
        if not result.success:
            return None

        for sub in result.subscriptions:
            if sub.name == 'chat.message.sent':
                if not webhook_url or not sub.webhook_url or sub.webhook_url == webhook_url:
                    return sub

        return None

    async def has_chat_subscription(self, webhook_url: str = '') -> bool:
        """Verifica se existe assinatura de chat.message.sent.

        Args:
            webhook_url: Verificar URL específica (opcional)

        Returns:
            True se assinatura existe (sem erro)
        """
        sub = await self.find_chat_message_subscription(webhook_url)
        return sub is not None


# Instância global
_subscriptions: KickSubscriptions | None = None


def get_subscriptions() -> KickSubscriptions:
    """Retorna instância global do gerenciador de assinaturas."""
    global _subscriptions
    if _subscriptions is None:
        _subscriptions = KickSubscriptions()
    return _subscriptions

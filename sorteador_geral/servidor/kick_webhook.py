"""Receptor de webhooks oficiais do Kick.

Validação de segurança:
- Assinatura RSA-SHA256 usando chave pública oficial
- Headers obrigatórios verificados
- Timestamp com janela de tolerância
- Deduplicação por message_id

Documentação:
https://github.com/KickEngineering/KickDevDocs/blob/main/events/webhook-security.md
https://github.com/KickEngineering/KickDevDocs/blob/main/events/event-types.md
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Callable
from urllib.request import urlopen
from urllib.error import URLError

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
import base64

logger = logging.getLogger(__name__)

# Configurações
PUBLIC_KEY_URL = 'https://api.kick.com/public/v1/public-key'
KEY_CACHE_TTL = 3600  # 1 hora
MAX_PAYLOAD_SIZE = 1024 * 1024  # 1MB
TIMESTAMP_TOLERANCE = 300  # 5 minutos
DEDUP_CACHE_SIZE = 10000
DEDUP_EXPIRY = 3600  # 1 hora


@dataclass
class KickWebhookEvent:
    """Evento de webhook parseado e validado."""
    event_type: str
    event_version: str
    message_id: str
    subscription_id: str
    timestamp: str
    broadcaster_user_id: str
    payload: dict

    # Campos extras para chat.message.sent
    sender_user_id: str = ''
    sender_username: str = ''
    sender_is_anonymous: bool = False
    message_content: str = ''
    message_created_at: str = ''


class WebhookDeduplicator:
    """Deduplicação de eventos por message_id."""

    def __init__(self, max_size: int = DEDUP_CACHE_SIZE, expiry: int = DEDUP_EXPIRY):
        self._cache: dict[str, float] = {}
        self._max_size = max_size
        self._expiry = expiry
        self._lock = asyncio.Lock()

    async def is_duplicate(self, message_id: str) -> bool:
        """Retorna True se o evento já foi processado."""
        async with self._lock:
            now = time.time()

            # Limpa entradas expiradas
            expired = [k for k, v in self._cache.items() if now - v > self._expiry]
            for k in expired:
                del self._cache[k]

            if message_id in self._cache:
                logger.debug(f'Duplicado ignorado: {message_id}')
                return True

            # Adiciona ao cache
            if len(self._cache) >= self._max_size:
                # Remove mais antigo
                oldest = min(self._cache, key=self._cache.get)
                del self._cache[oldest]

            self._cache[message_id] = now
            return False

    def clear(self) -> None:
        """Limpa o cache de deduplicação."""
        self._cache.clear()


class PublicKeyCache:
    """Cache da chave pública RSA do Kick."""

    def __init__(self, ttl: int = KEY_CACHE_TTL):
        self._key: str | None = None
        self._cached_at: float = 0
        self._ttl = ttl
        self._lock = asyncio.Lock()

    async def get_key(self, force_refresh: bool = False) -> str | None:
        """Retorna a chave pública, buscando do servidor se necessário."""
        async with self._lock:
            now = time.time()

            if not force_refresh and self._key and (now - self._cached_at) < self._ttl:
                return self._key

            try:
                logger.info('Buscando chave pública do Kick...')
                import httpx
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.get(PUBLIC_KEY_URL)
                    response.raise_for_status()
                if response.text.lstrip().startswith('-----BEGIN'):
                    self._key = response.text
                else:
                    result = response.json()
                    result = result.get('data', result)
                    self._key = result.get('public_key') or result.get('key')

                if not self._key:
                    logger.error('Chave pública não encontrada na resposta')
                    return None

                self._cached_at = now
                logger.info(f'Chave pública atualizada (cache TTL={self._ttl}s)')
                return self._key

            except URLError as e:
                logger.error(f'Falha ao buscar chave pública: {e!r}')
                # Retorna cache antigo se disponível
                return self._key
            except Exception as e:
                logger.error(f'Erro ao processar chave pública: {e!r}')
                return self._key

    def clear(self) -> None:
        """Limpa o cache."""
        self._key = None
        self._cached_at = 0


class KickWebhookValidator:
    """Validador de webhooks do Kick."""

    def __init__(
        self,
        timestamp_tolerance: int = TIMESTAMP_TOLERANCE,
        max_payload_size: int = MAX_PAYLOAD_SIZE,
    ):
        self._public_key_cache = PublicKeyCache()
        self._deduplicator = WebhookDeduplicator()
        self._timestamp_tolerance = timestamp_tolerance
        self._max_payload_size = max_payload_size

    async def validate_signature(
        self,
        message_id: str,
        timestamp: str,
        raw_body: bytes,
        signature_b64: str,
    ) -> tuple[bool, str]:
        """Valida a assinatura RSA-SHA256 do evento.

        Returns:
            (is_valid, error_message)
        """
        if not signature_b64:
            return False, 'Assinatura ausente'

        try:
            # Decodifica assinatura
            signature = base64.b64decode(signature_b64)
        except Exception as e:
            return False, f'Assinatura inválida (decode): {e!r}'

        try:
            # Busca chave pública
            public_key_pem = await self._public_key_cache.get_key()
            if not public_key_pem:
                return False, 'Chave pública indisponível'

            # Carrega chave pública RSA
            public_key = serialization.load_pem_public_key(
                public_key_pem.encode('utf-8'),
                backend=default_backend(),
            )

            # Monta dados assinados: message_id.timestamp.raw_body
            message_data = f'{message_id}.{timestamp}.{raw_body.decode("utf-8")}'.encode('utf-8')

            # Hash SHA-256 dos dados
            hashed = hashlib.sha256(message_data).digest()

            # Verifica assinatura
            public_key.verify(
                signature,
                message_data,
                padding.PKCS1v15(),
                hashes.SHA256(),
            )

            return True, ''

        except Exception as e:
            # A exceção pode vir de cryptography (InvalidSignature)
            return False, f'Assinatura inválida: {e!r}'

    async def validate_timestamp(self, timestamp_str: str) -> tuple[bool, str]:
        """Valida se o timestamp está dentro da janela de tolerância.

        Returns:
            (is_valid, error_message)
        """
        try:
            # Parse timestamp RFC3339
            from datetime import datetime, timezone
            event_time = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            if event_time.tzinfo is None:
                return False, 'Timestamp sem fuso horário'
            now = time.time()
            event_ts = event_time.timestamp()

            diff = abs(now - event_ts)
            if diff > self._timestamp_tolerance:
                return False, f'Timestamp fora da janela de tolerância ({diff:.0f}s)'

            return True, ''

        except Exception as e:
            return False, f'Timestamp inválido: {e!r}'

    async def validate_event(
        self,
        headers: dict,
        raw_body: bytes,
    ) -> tuple[bool, str, KickWebhookEvent | None]:
        """Valida um evento de webhook completo.

        Returns:
            (is_valid, error_message, event)
        """
        # 1. Verifica tamanho do payload
        if len(raw_body) > self._max_payload_size:
            return False, f'Payload excede {self._max_payload_size} bytes', None

        # 2. Extrai e verifica headers obrigatórios
        message_id = headers.get('Kick-Event-Message-Id', '')
        timestamp = headers.get('Kick-Event-Message-Timestamp', '')
        signature = headers.get('Kick-Event-Signature', '')
        event_type = headers.get('Kick-Event-Type', '')
        event_version = headers.get('Kick-Event-Version', '')
        subscription_id = headers.get('Kick-Event-Subscription-Id', '')

        if not message_id:
            return False, 'Header Kick-Event-Message-Id ausente', None
        if not timestamp:
            return False, 'Header Kick-Event-Message-Timestamp ausente', None
        if not signature:
            return False, 'Header Kick-Event-Signature ausente', None
        if not event_type:
            return False, 'Header Kick-Event-Type ausente', None


        # 4. Valida timestamp
        valid, msg = await self.validate_timestamp(timestamp)
        if not valid:
            return False, msg, None

        # 5. Valida assinatura
        valid, msg = await self.validate_signature(message_id, timestamp, raw_body, signature)
        if not valid:
            return False, f'Assinatura inválida: {msg}', None

        # 6. Parseia payload
        try:
            import json
            payload = json.loads(raw_body)
        except json.JSONDecodeError as e:
            return False, f'Payload JSON inválido: {e!r}', None

        if await self._deduplicator.is_duplicate(message_id):
            return False, 'Evento duplicado', None

        # 7. Cria evento
        event = KickWebhookEvent(
            event_type=event_type,
            event_version=event_version,
            message_id=message_id,
            subscription_id=subscription_id,
            timestamp=timestamp,
            broadcaster_user_id='',
            payload=payload,
        )

        # 8. Extrai campos específicos para chat.message.sent
        if event_type == 'chat.message.sent':
            self._parse_chat_message(event, payload)

        return True, '', event

    def _parse_chat_message(self, event: KickWebhookEvent, payload: dict) -> None:
        """Extrai campos do evento chat.message.sent."""
        # Broadcaster
        broadcaster = payload.get('broadcaster') or {}
        event.broadcaster_user_id = str(broadcaster.get('id', '') or broadcaster.get('user_id', ''))

        # Sender
        sender = payload.get('sender') or {}
        event.sender_user_id = str(sender.get('user_id', '') or sender.get('id', ''))
        event.sender_username = sender.get('username', '') or sender.get('name', '')
        event.sender_is_anonymous = sender.get('is_anonymous', True)

        # Content
        event.message_content = payload.get('content', '')

        # Created at
        event.message_created_at = payload.get('created_at', '')

    def get_broadcaster_id(self, event: KickWebhookEvent) -> str:
        """Retorna o broadcaster_user_id do evento."""
        return event.broadcaster_user_id


# Instância global
_validator: KickWebhookValidator | None = None


def get_validator() -> KickWebhookValidator:
    """Retorna instância global do validador."""
    global _validator
    if _validator is None:
        _validator = KickWebhookValidator()
    return _validator


def verify_broadcaster(event: KickWebhookEvent, expected_id: str) -> bool:
    """Verifica se o broadcaster_user_id do evento corresponde ao esperado."""
    if not expected_id:
        return True  # Sem configuração, aceita qualquer
    return event.broadcaster_user_id == str(expected_id)

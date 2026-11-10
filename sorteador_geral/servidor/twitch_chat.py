"""Conexão de chat Twitch via EventSub WebSocket.

Este aplicativo usa EventSub WebSocket, recomendado para bots instalados:
  - URL: wss://eventsub.wss.twitch.tv/ws
  - Conecta, recebe welcome com session_id
  - POST /helix/eventsub/subscriptions com transport={method:"websocket", session_id}
  - Eventos chegam como notification: { metadata.message_type, payload.event }

OAuth: precisa de USER ACCESS TOKEN com scope user:read:chat (ler chat).
O token também precisa de user:bot + channel:bot (de moderador/broadcaster) se for bot.

Referências:
- https://dev.twitch.tv/docs/eventsub/handling-websocket-events/
- https://dev.twitch.tv/docs/eventsub/eventsub-subscription-types/#channelchatmessage
- https://dev.twitch.tv/docs/api/reference/#create-eventsub-subscription
- https://id.twitch.tv/oauth2/validate (validação de token)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Callable, Awaitable

import httpx
import websockets

from . import twitch_api

logger = logging.getLogger(__name__)

TWITCH_EVENTSUB_WS = 'wss://eventsub.wss.twitch.tv/ws'
TWITCH_HELIX_BASE = 'https://api.twitch.tv/helix'


class TwitchAuthError(Exception):
    """Erro de autenticação do Twitch."""
    pass


class TokenExpiredError(TwitchAuthError):
    """Token expirado."""
    pass


class TokenInvalidError(TwitchAuthError):
    """Token inválido ou revogado."""
    pass


class ScopeMissingError(TwitchAuthError):
    """Token sem scope necessário."""
    def __init__(self, missing_scopes: list[str]):
        self.missing_scopes = missing_scopes
        super().__init__(f'Scopes ausentes: {", ".join(missing_scopes)}')

# Tipos de badge do EventSub chat.message → mesma semântica do IRC antigo
BADGE_SET_TO_FLAG = {
    'subscriber': 'is_sub',
    'founder': 'is_sub',
    'vip': 'is_vip',
    'moderator': 'is_mod',
    'broadcaster': 'is_broadcaster',
    # Badge partner não significa dono do canal.
    # Apenas broadcaster possui controle do canal.
}


@dataclass
class TwitchMessage:
    """Mensagem normalizada do chat da Twitch."""
    platform: str = 'twitch'
    username: str = ''
    display_name: str = ''
    user_id: str = ''
    color: str = '#ffffff'
    message: str = ''
    is_sub: bool = False
    is_vip: bool = False
    is_mod: bool = False
    is_owner: bool = False
    is_broadcaster: bool = False
    message_id: str = ''
    channel: str = ''
    source_channel: str = ''
    source_broadcaster_id: str = ''
    source_message_id: str = ''
    mentions: list = None
    badges: list = None

    def __post_init__(self):
        if self.badges is None:
            self.badges = []


def _badges_from_eventsub(badges: list) -> tuple[bool, bool, bool, bool, bool]:
    """Converte badges EventSub [{set_id,id,info}] em (sub, vip, mod, broadcaster, owner)."""
    is_sub = is_vip = is_mod = is_broadcaster = is_owner = False
    for b in badges or []:
        set_id = (b.get('set_id') or '').lower()
        if set_id in BADGE_SET_TO_FLAG:
            flag = BADGE_SET_TO_FLAG[set_id]
            if flag == 'is_sub': is_sub = True
            elif flag == 'is_vip': is_vip = True
            elif flag == 'is_mod': is_mod = True
            elif flag == 'is_broadcaster': is_broadcaster = True
            elif flag == 'is_owner': is_owner = True
    return is_sub, is_vip, is_mod, is_broadcaster, is_owner


def _parse_notification(payload: dict) -> TwitchMessage | None:
    """Converte payload.event de channel.chat.message em TwitchMessage."""
    if not payload:
        return None
    text = payload.get('message', {}).get('text', '')
    if not text:
        return None
    badges = payload.get('badges', []) or []
    is_sub, is_vip, is_mod, is_broadcaster, is_owner = _badges_from_eventsub(badges)
    return TwitchMessage(
        platform='twitch',
        username=payload.get('chatter_user_login', '').lower(),
        display_name=payload.get('chatter_user_name', '') or payload.get('chatter_user_login', ''),
        user_id=payload.get('chatter_user_id', ''),
        color=payload.get('color', '') or '#ffffff',
        message=text,
        message_id=payload.get('message_id', ''),
        channel=payload.get('broadcaster_user_login', ''),
        source_channel=payload.get('source_broadcaster_user_login') or payload.get('broadcaster_user_login', ''),
        source_broadcaster_id=payload.get('source_broadcaster_user_id') or '',
        source_message_id=payload.get('source_message_id') or '',
        mentions=[f.get('mention', {}).get('user_login', '') for f in payload.get('message', {}).get('fragments', []) if f.get('type') == 'mention' and f.get('mention')],
        is_sub=is_sub,
        is_vip=is_vip,
        is_mod=is_mod,
        is_owner=is_broadcaster,
        is_broadcaster=is_broadcaster,
        badges=[(b.get('set_id') or '') for b in badges],
    )


class TwitchChat:
    """Cliente EventSub WebSocket pra ler chat de um canal.

    Implementa:
    - Conexão EventSub WebSocket
    - session_reconnect (preserva assinaturas)
    - Deduplicação de mensagens (message_id)
    - Backoff exponencial para reconexões
    - Tratamento de revogação
    - Envio de mensagens com rate limiting
    """

    # Backoff inicial e máximo para reconexões (em segundos)
    BACKOFF_INITIAL = 5
    BACKOFF_MAX = 60

    # Rate limiting para envio de mensagens
    # Twitch limita a ~20 mensagens por 30 segundos
    SEND_COOLDOWN = 1.5  # segundos entre mensagens
    SEND_MAX_PER_WINDOW = 20  # mensagens por janela
    SEND_WINDOW = 30  # segundos

    # Tempo máximo para guardar message_ids (limpa periodicamente)
    MESSAGE_ID_TTL = 300  # 5 minutos

    def __init__(self):
        self.channel: str = ''
        self.broadcaster_id: str = ''  # Twitch user_id numérico do canal
        self.user_id: str = ''  # Twitch user_id do token usado
        self.connected: bool = False  # True apenas quando assinatura está ativa
        self._should_run: bool = False
        self._on_message: Callable[[TwitchMessage], Awaitable[None]] | None = None
        self._generation: int = 0
        # credenciais (Token = user OAuth com scope user:read:chat)
        self.client_id: str = ''
        self.token: str = ''
        # Deduplicação de mensagens
        self._seen_message_ids: set[str] = set()
        self._last_cleanup: float = time.time()
        # Flag para revogação (não reconecta automaticamente)
        self._revoked: bool = False
        # Lock para evitar reconexões simultâneas
        self._reconnect_lock: asyncio.Lock = asyncio.Lock()
        # Rate limiting para envio de mensagens
        self._send_timestamps: list[float] = []
        self._can_send: bool = True  # False se token não tem user:write:chat
        self._send_lock = asyncio.Lock()

    def set_callback(self, cb: Callable[[TwitchMessage], Awaitable[None]]) -> None:
        self._on_message = cb

    def set_credentials(self, client_id: str = '', token: str = '') -> None:
        self.client_id = client_id.strip()
        self.token = twitch_api.normalize_token(token)

    async def _validate_credentials(self, client_id: str, token: str) -> twitch_api.TokenInfo:
        """Valida credenciais e verifica scopes antes de conectar.

        Raises:
            TokenInvalidError: Token inválido, expirado ou revogado
            ScopeMissingError: Scope user:read:chat ausente
            TwitchAuthError: Client ID não corresponde ao token
        """
        # Valida o token
        token_info = await twitch_api.validate_token(client_id, token)

        if token_info is None:
            raise TokenInvalidError(
                'Token inválido, expirado ou revogado. '
                'Cole o Access token (não Refresh token) de uma autorização da Twitch. Em Conexões, use Identificar Client ID do token para conferir o aplicativo e os escopos.'
            )

        if not token_info.user_id:
            raise TwitchAuthError('O token é de aplicativo. Use um User Access Token da conta que vai ler/escrever no chat.')

        # Verifica se o Client ID do token corresponde ao configurado
        if token_info.client_id and token_info.client_id != client_id:
            logger.warning(
                f'Client ID mismatch: config={client_id}, token={token_info.client_id}'
            )
            raise TwitchAuthError('O Client-ID deve pertencer ao aplicativo que emitiu este token.')

        # Verifica scope mínimo necessário (user:read:chat)
        missing_scopes = []
        if not token_info.has_read_chat:
            missing_scopes.append('user:read:chat')

        if missing_scopes:
            raise ScopeMissingError(missing_scopes)

        return token_info

    async def connect(self, channel: str, client_id: str = '', token: str = '') -> None:
        """Conecta ao chat de um canal via EventSub WebSocket.

        Requer client_id + token (user OAuth) configurados antes ou aqui.
        Sem token = não conecta (EventSub não tem modo anônimo).

        Raises:
            TokenInvalidError: Token inválido, expirado ou revogado
            ScopeMissingError: Scope user:read:chat ausente
            ValueError: Credenciais ausentes ou canal inválido
        """
        channel = channel.strip().lstrip('#@').lower()
        if not re.fullmatch(r'[a-z0-9_]{1,25}', channel):
            raise ValueError(f'Canal Twitch inválido: {channel!r}')

        # Define credenciais
        if client_id:
            self.client_id = client_id.strip()
        if token:
            self.set_credentials(self.client_id, token)

        if not self.client_id or not self.token:
            raise ValueError(
                'Twitch EventSub exige Client-ID + OAuth token. '
                'Configure em Conexões.'
            )

        # Valida o token antes de conectar
        token_info = await self._validate_credentials(self.client_id, self.token)
        logger.info(
            f'Token validado: user_id={token_info.user_id}, '
            f'scopes={len(token_info.scopes)}, '
            f'read_chat={token_info.has_read_chat}, '
            f'write_chat={token_info.has_write_chat}'
        )
        # Define se pode enviar mensagens
        self.user_login = token_info.login
        self._can_send = token_info.has_write_chat
        if not token_info.has_write_chat:
            logger.warning('Scope user:write:chat ausente - envio de mensagens desabilitado')

        # Já tá conectado no mesmo canal
        if self.connected and self.channel == channel:
            return

        self._generation += 1
        gen = self._generation
        self._should_run = False
        await asyncio.sleep(0.1)
        self._should_run = True
        self.channel = channel
        self.broadcaster_id = ''
        self.user_id = ''

        asyncio.create_task(self._run(gen))

    async def disconnect(self) -> None:
        """Desconecta e para todas as tentativas de reconexão."""
        self._should_run = False
        self._revoked = False  # Reset para permitir reconexão futura
        self.connected = False
        self._generation += 1
        self._seen_message_ids.clear()
        self._send_timestamps.clear()
        logger.info('Twitch: desconectado')

    async def _run(self, generation: int) -> None:
        """Loop principal com backoff exponencial para reconexões."""
        backoff = self.BACKOFF_INITIAL

        while self._should_run and generation == self._generation:
            # Verifica se foi revogado (não tenta reconectar)
            if self._revoked:
                logger.error('Twitch: assinatura revogada. Desconecte e reconecte manualmente.')
                return

            try:
                await self._connect_once(generation)
                # Se chegou aqui, conexão foi bem sucedida - reseta backoff
                backoff = self.BACKOFF_INITIAL
            except TokenInvalidError as e:
                if generation != self._generation:
                    return
                logger.error(f'Twitch: {e}. Configure novas credenciais.')
                self.connected = False
                return
            except ScopeMissingError as e:
                if generation != self._generation:
                    return
                logger.error(f'Twitch: {e}. Solicite o scope necessário ao gerar o token.')
                self.connected = False
                return
            except TwitchAuthError as e:
                if generation != self._generation:
                    return
                logger.error(f'Twitch auth error: {e}')
                self.connected = False
                return
            except Exception as e:
                if generation != self._generation:
                    return
                logger.warning(f'Twitch: erro na conexão: {e!r}')

            if not self._should_run or generation != self._generation:
                return

            self.connected = False
            # Backoff exponencial com máximo
            logger.info(f'Twitch: reconectando em {backoff}s...')
            await asyncio.sleep(backoff)
            backoff = min(self.BACKOFF_MAX, backoff * 2)

    async def _get_user_id(self, login: str) -> str:
        """Busca user_id numérico da Twitch pelo login. Requer client_id + token."""
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(
                f'{TWITCH_HELIX_BASE}/users',
                params={'login': login},
                headers={
                    'Authorization': f'Bearer {self.token}',
                    'Client-Id': self.client_id,
                },
            )
            if r.status_code != 200:
                raise RuntimeError(f'Helix /users status {r.status_code}: {r.text[:200]}')
            data = r.json().get('data') or []
            if not data:
                raise RuntimeError(f'Canal "{login}" não encontrado na Twitch')
            return data[0]['id']

    async def _subscribe_chat(self, session_id: str, broadcaster_id: str, user_id: str) -> dict:
        """Cria subscription channel.chat.message via WebSocket transport.

        Returns:
            dict com info da subscription (inclui 'status' e 'id')
            ou levanta RuntimeError se falhar.

        Raises:
            RuntimeError: Se a API retornar erro ou subscription não ficar enabled
        """
        body = {
            'type': 'channel.chat.message',
            'version': '1',
            'condition': {
                'broadcaster_user_id': broadcaster_id,
                'user_id': user_id,  # o bot (quem tem o token) tem que ser moderador/broadcaster
            },
            'transport': {
                'method': 'websocket',
                'session_id': session_id,
            },
        }
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(
                f'{TWITCH_HELIX_BASE}/eventsub/subscriptions',
                json=body,
                headers={
                    'Authorization': f'Bearer {self.token}',
                    'Client-Id': self.client_id,
                    'Content-Type': 'application/json',
                },
            )

            # Lê o corpo da resposta antes de fechar
            response_data = r.json() if r.content else {}

            if r.status_code in (200, 201, 202, 204):
                # Verifica se a subscription ficou enabled
                sub_data = response_data.get('data', [{}])[0] if response_data.get('data') else {}
                status = sub_data.get('status', 'enabled')
                sub_id = sub_data.get('id', 'unknown')

                if status != 'enabled':
                    raise RuntimeError(
                        f'Subscription criada mas status={status} (não enabled). '
                        f'ID: {sub_id}'
                    )

                logger.info(
                    f'Twitch: subscrição criada (id={sub_id[:8]}..., '
                    f'status={status}, broadcaster={broadcaster_id}, bot={user_id})'
                )
                return {'id': sub_id, 'status': status}

            # 409 = subscrição já existe (pode ser de outra sessão)
            if r.status_code == 409:
                logger.info('Twitch: subscrição já existia (409), continuando')
                return {'id': 'existing', 'status': 'exists'}

            # Outros erros
            error_msg = response_data.get('message', r.text[:200])
            raise RuntimeError(
                f'Helix subscribe falhou: status={r.status_code}, error={error_msg}'
            )

    async def _connect_once(self, generation: int, reconnect_url: str | None = None) -> None:
        """Conecta ao EventSub WebSocket e mantém conexão ativa.

        Args:
            generation: Geração desta conexão (para cancelamento)
            reconnect_url: URL para session_reconnect (None = conexão nova)

        A propriedade connected (is_connected) só fica True APÓS a subscription
        estar criada e enabled. Se a subscription falhar, connected permanece False.
        """
        # 1. resolve IDs (apenas na primeira conexão, não em reconnect)
        if not self.broadcaster_id or not self.user_id:
            broadcaster_id = await self._get_user_id(self.channel)
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(
                    f'{TWITCH_HELIX_BASE}/users',
                    headers={
                        'Authorization': f'Bearer {self.token}',
                        'Client-Id': self.client_id,
                    },
                )
                if r.status_code != 200:
                    raise RuntimeError(f'Helix /users (self) status {r.status_code}')
                me = (r.json().get('data') or [{}])[0]
                bot_user_id = me.get('id', '')
            if not bot_user_id:
                raise RuntimeError('Não consegui resolver o user_id do token')
            self.broadcaster_id = broadcaster_id
            self.user_id = bot_user_id

        broadcaster_id = self.broadcaster_id
        bot_user_id = self.user_id

        # 2. conecta WS (na reconnect_url se fornecida, senão padrão)
        ws_url = reconnect_url or TWITCH_EVENTSUB_WS
        if reconnect_url:
            logger.info(f'Twitch: reconnect para {reconnect_url[:50]}...')
        else:
            logger.info(f'Twitch: conectando EventSub (canal={self.channel}, broadcaster={broadcaster_id}, bot={bot_user_id})...')

        ws = await websockets.connect(
            ws_url,
            ping_interval=30,
            ping_timeout=10,
            close_timeout=5,
        )
        # NÃO marca connected aqui - só após subscription estar ativa
        try:
            # 3. welcome
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            msg = json.loads(raw)
            if msg.get('metadata', {}).get('message_type') != 'session_welcome':
                raise RuntimeError(f'Primeira msg não foi welcome: {msg}')
            session_id = msg['payload']['session']['id']
            keepalive = msg['payload']['session'].get('keepalive_timeout_seconds', 10)
            logger.info(f'Twitch: session_welcome id={session_id[:8]}... keepalive={keepalive}s')

            # 4. Se reconnect, as assinaturas são preservadas automaticamente
            if reconnect_url:
                logger.info('Twitch: reconnect bem-sucedido, assinaturas preservadas')
            else:
                # Primeira conexão: cria subscription
                await self._subscribe_chat(session_id, broadcaster_id, bot_user_id)

            # 5. Subscription criada/verificada - marca como conectado
            self.connected = True
            self._revoked = False  # Reset flag de revogação
            logger.info(f'Twitch: conectado (canal={self.channel}, session={session_id[:8]}...)')

            # 6. loop de leitura
            while self._should_run and generation == self._generation:
                try:
                    # Usa keepalive_timeout + buffer para timeout
                    recv_timeout = keepalive + 10
                    raw = await asyncio.wait_for(ws.recv(), timeout=recv_timeout)
                except asyncio.TimeoutError:
                    logger.warning('Twitch: timeout em recv(), reconectando...')
                    break

                try:
                    m = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                meta = m.get('metadata', {})
                mtype = meta.get('message_type')

                if mtype == 'session_keepalive':
                    # Limpa IDs antigos periodicamente
                    self._cleanup_message_ids()
                    continue

                if mtype == 'session_reconnect':
                    reconnect_url_new = m.get('payload', {}).get('session', {}).get('reconnect_url')
                    logger.info(f'Twitch: session_reconnect → {reconnect_url_new}')
                    if reconnect_url_new:
                        # Reconecta para a nova URL (mantém esta conexão aberta)
                        replacement = await self._handle_reconnect(generation, reconnect_url_new, ws)
                        if replacement:
                            ws, keepalive = replacement
                            continue
                    break

                if mtype == 'notification' and meta.get('subscription_type') == 'channel.chat.message':
                    event = m.get('payload', {}).get('event') or {}
                    # Deduplicação por message_id
                    msg_id = meta.get('message_id', '')
                    if msg_id and msg_id in self._seen_message_ids:
                        logger.debug(f'Twitch: mensagem duplicada ignorada: {msg_id[:8]}...')
                        continue
                    if msg_id:
                        self._seen_message_ids.add(msg_id)

                    parsed = _parse_notification(event)
                    if parsed and self._on_message:
                        try:
                            await self._on_message(parsed)
                        except Exception as e:
                            logger.error(f'callback erro: {e!r}')

                elif mtype == 'revocation':
                    sub_status = m.get('payload', {}).get('subscription', {}).get('status', 'unknown')
                    sub_type = m.get('payload', {}).get('subscription', {}).get('type', 'unknown')
                    logger.warning(f'Twitch: assinatura revogada: type={sub_type}, status={sub_status}')
                    # Marca como revogado para não reconectar automaticamente
                    self._revoked = True
                    self.connected = False
                    break

        finally:
            self.connected = False  # Garante que fica False ao sair
            try: await ws.close()
            except Exception: pass

    async def _handle_reconnect(self, generation: int, reconnect_url: str, old_ws):
        """Trata session_reconnect: conecta na nova URL e preserva assinaturas."""
        try:
            logger.info(f'Twitch: conectando na nova URL...')
            new_ws = await websockets.connect(
                reconnect_url,
                ping_interval=30,
                ping_timeout=10,
                close_timeout=5,
            )

            # Aguarda welcome na nova conexão
            raw = await asyncio.wait_for(new_ws.recv(), timeout=10)
            msg = json.loads(raw)
            if msg.get('metadata', {}).get('message_type') != 'session_welcome':
                logger.warning('Twitch: welcome não veio na reconnect URL')
                await new_ws.close()
                return

            new_session_id = msg['payload']['session']['id']
            new_keepalive = msg['payload']['session'].get('keepalive_timeout_seconds', 10)
            logger.info(f'Twitch: reconnect OK, nova session={new_session_id[:8]}...')

            # Encerra conexão antiga
            try:
                await old_ws.close()
            except Exception:
                pass

            return new_ws, new_keepalive

            # Substitui a conexão antiga pela nova
            # Nota: as assinaturas são automaticamente transferidas
            # Continua no loop de leitura com a nova conexão

        except Exception as e:
            logger.warning(f'Twitch: reconnect falhou: {e!r}')

    def _cleanup_message_ids(self) -> None:
        """Limpa periodicamente IDs de mensagens antigas."""
        now = time.time()
        if now - self._last_cleanup < 60:  # Limpa no máximo a cada 60s
            return
        # Reduz o set se cresceu demais
        if len(self._seen_message_ids) > 10000:
            # Mantém apenas os 5000 mais recentes (clear total por simplicidade)
            self._seen_message_ids.clear()
        self._last_cleanup = now

    @property
    def is_connected(self) -> bool:
        return self.connected

    @property
    def can_send_messages(self) -> bool:
        """Verifica se o token permite envio de mensagens.

        True: confirmado que pode enviar
        False: confirmado que NÃO pode enviar (reconecte para re-verificar)
        """
        if not self._can_send:
            return False
        return bool(self.token and self.broadcaster_id and self.user_id)

    async def _check_write_permission(self) -> bool:
        """Verifica se o token tem scope user:write:chat via validate."""
        try:
            token_info = await twitch_api.validate_token(self.client_id, self.token)
            if token_info is None:
                self._can_send = False
                return False
            has_write = token_info.has_write_chat
            self._can_send = has_write
            if not has_write:
                logger.warning('Token sem scope user:write:chat - envio de mensagens desabilitado')
            return has_write
        except Exception as e:
            logger.warning(f'Erro ao verificar permissao de escrita: {e!r}')
            return False

    def _check_rate_limit(self) -> bool:
        """Verifica rate limit. Retorna True se pode enviar, False se precisa esperar."""
        now = time.time()
        window_start = now - self.SEND_WINDOW

        # Remove mensagens antigas do histórico
        self._send_timestamps = [t for t in self._send_timestamps if t > window_start]

        # Verifica se está dentro do limite
        if len(self._send_timestamps) >= self.SEND_MAX_PER_WINDOW:
            return False

        # Se enviou recentemente, verifica cooldown
        if self._send_timestamps and (now - self._send_timestamps[-1]) < self.SEND_COOLDOWN:
            return False

        return True

    def _record_send(self) -> None:
        """Registra que uma mensagem foi enviada (para rate limiting)."""
        self._send_timestamps.append(time.time())
        # Limita tamanho da lista
        if len(self._send_timestamps) > self.SEND_MAX_PER_WINDOW * 2:
            self._send_timestamps = self._send_timestamps[-self.SEND_MAX_PER_WINDOW:]

    async def send_message(self, text: str) -> dict:
        async with self._send_lock:
            now = time.time()
            active = [ts for ts in self._send_timestamps if ts > now-self.SEND_WINDOW]
            delay = max(0, active[-1]+self.SEND_COOLDOWN-now) if active else 0
            if len(active) >= self.SEND_MAX_PER_WINDOW:
                delay = max(delay, active[0]+self.SEND_WINDOW-now+.01)
            if delay: await asyncio.sleep(delay)
            return await self._send_message(text)

    async def _send_message(self, text: str) -> dict:
        """Envia mensagem no chat via Helix (POST /chat/messages).

        Args:
            text: Texto da mensagem a enviar

        Returns:
            dict com keys:
                - success: bool (True se enviou com sucesso)
                - is_sent: bool (True se a Twitch confirmou envio)
                - error: str|None (descrição do erro, se houver)
                - rate_limited: bool (True se atingiu rate limit)
                - no_permission: bool (True se token não tem permissão)
        """
        result = {
            'success': False,
            'is_sent': False,
            'error': None,
            'rate_limited': False,
            'no_permission': False,
        }

        # Verifica credenciais básicas
        if not self.token or not self.broadcaster_id or not self.user_id:
            result['error'] = 'Credenciais não configuradas'
            return result

        if not text:
            result['error'] = 'Mensagem vazia'
            return result

        # Verifica se pode enviar (permissão verificada anteriormente)
        # Se False, não pode enviar (reconecte para re-verificar)
        if not self._can_send:
            result['no_permission'] = True
            result['error'] = 'Sem permissao de escrita (reconecte para verificar)'
            return result

        # Verifica rate limiting
        if not self._check_rate_limit():
            result['rate_limited'] = True
            result['error'] = 'Rate limit atingido, aguarde'
            return result

        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.post(
                    f'{TWITCH_HELIX_BASE}/chat/messages',
                    json={
                        'broadcaster_id': self.broadcaster_id,
                        'sender_id': self.user_id,
                        'message': text,
                    },
                    headers={
                        'Authorization': f'Bearer {self.token}',
                        'Client-Id': self.client_id,
                        'Content-Type': 'application/json',
                    },
                )

                # 200 OK: API retorna JSON com status da mensagem
                # is_sent=True explicitamente confirma envio
                if r.status_code == 200:
                    try:
                        response_data = r.json() if r.content else {}
                    except Exception:
                        result['error'] = 'Resposta JSON invalida'
                        return result

                    # Verifica estrutura da resposta
                    data_list = response_data.get('data')
                    if not data_list or not isinstance(data_list, list) or len(data_list) == 0:
                        result['error'] = 'Resposta inesperada: data vazia ou invalida'
                        return result

                    sent_data = data_list[0]

                    # is_sent DEVE ser o booleano True para considerar sucesso
                    if sent_data.get('is_sent') is not True:
                        drop_reason = sent_data.get('drop_reason')
                        reason_str = drop_reason or 'is_sent nao e True'
                        result['error'] = f'Mensagem nao enviada: {reason_str}'
                        result['is_sent'] = False
                        return result

                    # is_sent=True - mensagem enviada com sucesso
                    self._record_send()
                    result['message_id'] = sent_data.get('message_id','')
                    result['success'] = True
                    result['is_sent'] = True
                    return result

                # 204 No Content: resposta inesperada da API
                # Nao declara sucesso para evitar duplicacao
                if r.status_code == 204:
                    result['error'] = 'Resposta inesperada (204): mensagem pode nao ter sido enviada'
                    return result

                # Lê resposta de erro
                error_data = {}
                try:
                    error_data = r.json()
                except Exception:
                    pass
                error_msg = error_data.get('message', r.text[:200])

                # 400 - Bad Request (mensagem muito longa, etc)
                if r.status_code == 400:
                    result['error'] = f'Requisicao invalida: {error_msg}'
                    return result

                # 401 - Unauthorized (token inválido ou expirado)
                # Bloqueia - usuário deve reconectar com novo token
                if r.status_code == 401:
                    result['no_permission'] = True
                    result['error'] = 'Token invalido ou expirado (reconecte para continuar)'
                    self._can_send = False
                    return result

                # 403 - Forbidden (sem permissão de escrita no canal)
                # Bloqueia - usuário deve reconectar com permissões corretas
                if r.status_code == 403:
                    result['no_permission'] = True
                    result['error'] = 'Sem permissao para enviar (precisa ser mod/broadcaster)'
                    self._can_send = False
                    return result

                # 429 - Too Many Requests
                if r.status_code == 429:
                    result['rate_limited'] = True
                    retry_after = error_data.get('retry_after', 1)
                    result['error'] = f'Rate limit atingido, retry_after={retry_after}s'
                    return result

                # Outros erros
                result['error'] = f'Erro {r.status_code}: {error_msg}'
                return result

        except httpx.TimeoutException:
            result['error'] = 'Timeout ao enviar mensagem'
            return result
        except httpx.ConnectError:
            result['error'] = 'Erro de conexão'
            return result
        except Exception as e:
            result['error'] = f'Erro inesperado: {e!r}'
            return result

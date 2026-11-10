"""Kick: conexão direta pública, webhooks opcionais e envio pela API oficial.

O transporte direto recebe mensagens do protocolo Pusher usado pelo chat web.
Não utiliza cookies, tokens privados do site ou contorno de bloqueios.
"""
from __future__ import annotations

import asyncio
import logging
import re
import json
import uuid
import time
import websockets
from dataclasses import dataclass
from typing import Callable, Awaitable

import httpx

logger = logging.getLogger(__name__)
PUSHER_URL = "wss://ws-us2.pusher.com/app/32cbd69e4b950bf97679?protocol=7&client=js&version=8.4.0&flash=false"


@dataclass
class KickMessage:
    """Mensagem normalizada do chat da Kick."""
    platform: str = 'kick'
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
    badges: list = None

    def __post_init__(self):
        if self.badges is None:
            self.badges = []


def _badges_from_kick(badges: list) -> tuple[bool, bool, bool, bool]:
    """Lê lista de badges (ex: [{type:'subscriber'}, {type:'vip'}]) e retorna (sub, vip, mod, broadcaster)."""
    types = {b.get('type', '').lower() for b in (badges or [])}
    return (
        'subscriber' in types or 'founder' in types,
        'vip' in types,
        'moderator' in types,
        'broadcaster' in types,
    )


class KickChat:
    """Leitura direta ou por webhook, com envio OAuth independente."""

    def __init__(self):
        self.channel: str = ''
        self.chatroom_id: int | None = None
        self.channel_id: int | None = None
        self.transport = 'pusher'
        self._refresh_at = 0.0
        self.connected: bool = False
        self._should_run: bool = False
        self._on_message: Callable[[KickMessage], Awaitable[None]] | None = None
        self._client: httpx.AsyncClient | None = None
        self.mode = 'direct'
        self.broadcaster_user_id = ''
        self.last_error = ''
        self.last_send_error = ''
        self.last_sent_message_id = ''
        self._socket = None
        self._task = None
        self._seen = {}

    def set_callback(self, cb: Callable[[KickMessage], Awaitable[None]]) -> None:
        self._on_message = cb

    async def connect(self, channel: str, simulate: bool = True, *, mode: str = 'direct', chatroom_id: int | None = None, channel_id: int | None = None) -> None:
        channel = channel.strip().lstrip('@').lower()
        if not re.fullmatch(r'[a-z0-9_-]{1,50}',channel):
            raise ValueError('Informe somente o nome do canal da Kick, sem URL.')
        await self.disconnect()
        if channel != self.channel:self._seen.clear()
        self.channel = channel
        self.mode = mode
        self.chatroom_id = None
        self.channel_id = channel_id
        self.broadcaster_user_id = ''
        self.last_error = ''
        self._should_run = True
        if simulate:
            self._task = asyncio.create_task(self._run_simulated())
            return
        if mode == 'direct':
            try:
                if chatroom_id:
                    self.chatroom_id = chatroom_id
                    if not channel_id:
                        try:
                            await self._fetch_chatroom_id()
                        except (ValueError, httpx.HTTPError) as error:
                            raise ValueError('Informe também o ID do canal (campo id da resposta pública), além de chatroom.id, para conectar ao realtime da Kick.') from error
                else:
                    await self._fetch_chatroom_id()
                if not self.chatroom_id:
                    raise ValueError('Não foi possível identificar a sala. Informe o ID da sala em Opções avançadas.')
                await self._open_direct()
                self._task = asyncio.create_task(self._run_direct())
                return
            except Exception as error:
                await self.disconnect()
                self.last_error = str(error) or 'A conexão direta não respondeu. Tente novamente ou use Webhooks.'
                raise ValueError(self.last_error) from error
        from .kick_chat_auth import get_kick_auth
        from .ngrok_manager import is_ngrok_connected
        from .state import STATE
        status = get_kick_auth().get_status()
        if not status.is_authenticated or not status.has_events_subscribe:
            await self.disconnect()
            raise ValueError('Autorize a conta Kick com events:subscribe.')
        if not is_ngrok_connected() or not getattr(STATE,'kick_subscription_state',{}).get('subscription_registered'):
            await self.disconnect()
            raise ValueError('Ative o túnel e a assinatura chat.message.sent em Conexões.')
        self.connected = True

    async def disconnect(self) -> None:
        self._should_run = False
        self.connected = False
        if self._task:
            self._task.cancel()
            try:await self._task
            except asyncio.CancelledError:pass
            self._task = None
        if self._socket:
            await self._socket.close()
            self._socket = None
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _open_direct(self) -> None:
        """Confirma a assinatura antes de declarar conexão ao chat público."""
        if self.channel_id:
            await self._open_realtime()
            return
        self.transport = 'pusher'
        self._socket = await websockets.connect(
            PUSHER_URL, open_timeout=12, close_timeout=3, ping_interval=20, ping_timeout=20,
            max_size=2**20)
        try:
            packet = json.loads(await asyncio.wait_for(self._socket.recv(), 12))
            if packet.get('event') != 'pusher:connection_established':
                raise RuntimeError('A Kick não confirmou a conexão direta.')
            await self._socket.send(json.dumps({'event':'pusher:subscribe','data':{
                'auth':'','channel':f'chatrooms.{self.chatroom_id}.v2'}}))
            deadline = asyncio.get_running_loop().time()+12
            while True:
                remaining = deadline-asyncio.get_running_loop().time()
                if remaining<=0:raise asyncio.TimeoutError('A Kick não confirmou a assinatura do chat.')
                packet = json.loads(await asyncio.wait_for(self._socket.recv(),remaining))
                if packet.get('event') == 'pusher_internal:subscription_succeeded':
                    if packet.get('channel') != f'chatrooms.{self.chatroom_id}.v2':
                        continue
                    self.connected = True
                    self.last_error = ''
                    return
                if packet.get('event') in ('pusher:error','pusher:subscription_error'):
                    raise RuntimeError('A Kick recusou a assinatura do chat público.')
                await self._handle_packet(packet)
        except BaseException:
            await self._socket.close()
            self._socket = None
            raise

    async def _open_realtime(self) -> None:
        """Negocia credencial pública efêmera, sem token OAuth ou cookie do usuário."""
        client_id = str(uuid.uuid4())
        base = 'https://web.kick.com/api/v1/realtime'
        async with httpx.AsyncClient(timeout=12, headers={
            'Accept': 'application/json', 'Origin': 'https://kick.com',
            'Referer': 'https://kick.com/', 'x-app-platform': 'web',
            'User-Agent': 'SorteadorGeral/0.9'}) as client:
            descriptor = await client.post(f'{base}/channels/{self.channel_id}/chat/connection', json={
                'client': {'id': client_id, 'type': 'web'},
                'capabilities': {'accepted_providers': [{'provider': 'centrifugo'}]}})
            auth = await client.post(f'{base}/auth/connection', json={'client_id': client_id})
        if descriptor.status_code != 200 or auth.status_code != 200:
            raise ValueError(f'A Kick recusou a conexão realtime (HTTP {descriptor.status_code}/{auth.status_code}). Tente novamente ou use Webhooks.')
        connections = (descriptor.json().get('data') or {}).get('connections') or []
        connection = next((c for c in connections if c.get('provider') == 'centrifugo'), {})
        url = (connection.get('credentials') or {}).get('url', '')
        token = (auth.json().get('data') or {}).get('token')
        if not isinstance(url, str) or not url.startswith('wss://') or not token:
            raise ValueError('A Kick não retornou uma conexão realtime válida.')
        self.transport = 'centrifugo'
        self._refresh_at = 0
        self._socket = await websockets.connect(url, open_timeout=12, close_timeout=3,
            ping_interval=20, ping_timeout=20, max_size=2**20)
        try:
            await self._socket.send(json.dumps({'id': 1, 'connect': {
                'token': token, 'name': 'sorteador-geral', 'version': '0.9'}}))
            deadline = asyncio.get_running_loop().time() + 15
            while not self.connected:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise ValueError('A Kick não confirmou a assinatura realtime do chat.')
                raw = await asyncio.wait_for(self._socket.recv(), remaining)
                await self._handle_realtime(raw)
        except BaseException:
            await self._socket.close()
            self._socket = None
            raise

    async def _handle_realtime(self, raw) -> None:
        # Centrifugo pode agrupar vários objetos JSON separados por nova linha.
        for line in raw.splitlines():
            try:
                frame = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(frame, dict):
                continue
            if not frame:
                await self._socket.send('{}')
                continue
            if frame.get('error'):
                raise ValueError('A Kick recusou a conexão ou assinatura realtime. Reconectando...')
            if frame.get('id') == 1 and 'connect' in frame:
                ttl = (frame['connect'] or {}).get('ttl', 0)
                if isinstance(ttl, (int, float)) and ttl > 0:
                    self._refresh_at = time.monotonic() + max(1, ttl - min(60, ttl / 2))
                await self._socket.send(json.dumps({'id': 2, 'subscribe': {
                    'channel': f'chatrooms.{self.chatroom_id}.v2'}}))
            if frame.get('id') == 2 and 'subscribe' in frame:
                self.connected = True
                self.last_error = ''
            push = frame.get('push') or {}
            if 'disconnect' in push or 'unsubscribe' in push:
                raise ValueError('A Kick encerrou a assinatura realtime. Reconectando...')
            publication = push.get('pub') or {}
            envelope = publication.get('data')
            if isinstance(envelope, str):
                try: envelope = json.loads(envelope)
                except ValueError: continue
            if not isinstance(envelope, dict):
                continue
            channel = push.get('channel') or f'chatrooms.{self.chatroom_id}.v2'
            await self._handle_packet({**envelope, 'channel': channel})

    async def _handle_packet(self, packet: dict) -> None:
        event = packet.get('event')
        if event == 'pusher:ping':
            await self._socket.send(json.dumps({'event':'pusher:pong','data':{}}))
            return
        if event != 'App\\Events\\ChatMessageEvent':
            return
        if packet.get('channel') != f'chatrooms.{self.chatroom_id}.v2':
            return
        data = packet.get('data') or {}
        if isinstance(data,str):
            try:data = json.loads(data)
            except (ValueError,TypeError):return
        if not isinstance(data,dict):return
        sender = data.get('sender') or {}
        identity = sender.get('identity') or {}
        username = str(sender.get('username') or '').strip()
        content = data.get('content')
        if not username or not isinstance(content,str):return
        message_id = str(data.get('id') or '')
        if message_id and message_id in self._seen:return
        if message_id:
            self._seen[message_id] = None
            if len(self._seen)>1000:self._seen.pop(next(iter(self._seen)))
        badges = identity.get('badges') or sender.get('badges') or []
        sub,vip,mod,owner = _badges_from_kick([b for b in badges if isinstance(b,dict)])
        message = KickMessage(username=username.lower(),display_name=username,
            user_id=str(sender.get('id') or ''),message=content,message_id=message_id,
            color=identity.get('color') or '#ffffff',is_sub=sub,is_vip=vip,is_mod=mod,
            is_owner=owner,is_broadcaster=owner,badges=badges)
        if self._on_message:await self._on_message(message)

    async def _run_direct(self) -> None:
        delay = 1
        try:
            while self._should_run:
                try:
                    if self._socket is None:
                        await self._open_direct()
                    delay = 1
                    while self._should_run:
                        if self.transport == 'centrifugo' and self._refresh_at and time.monotonic() >= self._refresh_at:
                            raise RuntimeError('Renovando conexão pública da Kick')
                        try:raw = await asyncio.wait_for(self._socket.recv(),25)
                        except asyncio.TimeoutError:
                            if self.transport == 'pusher':
                                await self._socket.send(json.dumps({'event':'pusher:ping','data':{}}))
                            continue
                        if self.transport == 'centrifugo':
                            try: await self._handle_realtime(raw)
                            except (ValueError, RuntimeError): raise
                            except Exception: logger.exception('Kick: falha ao processar mensagem realtime')
                            continue
                        try:packet = json.loads(raw)
                        except (ValueError,TypeError):continue
                        if not isinstance(packet,dict):continue
                        try:await self._handle_packet(packet)
                        except Exception:logger.exception('Kick: falha ao processar mensagem recebida')
                except asyncio.CancelledError:raise
                except Exception:
                    self.connected = False
                    self.last_error = 'Conexão direta interrompida. Tentando reconectar...'
                    if self._socket:
                        await self._socket.close()
                        self._socket = None
                    if not self._should_run:break
                    await asyncio.sleep(delay)
                    delay = min(delay*2,30)
        finally:
            self.connected = False

    async def _run_simulated(self) -> None:
        """Loop que gera mensagens falsas pra testar a UI."""
        # Primeiro tenta buscar o chatroom_id real (a API pública do Kick
        # /api/v1/channels/<slug> ainda funciona sem auth)
        try:
            await self._fetch_chatroom_id()
        except Exception as e:
            logger.warning(f'Kick simulado: não consegui chatroom_id ({e!r}), seguindo sem ele')

        await asyncio.sleep(2)  # tempo de "conexão"
        if not self._should_run:
            return

        self.connected = True
        logger.info(f'Kick simulado: conectado em @{self.channel} (chatroom_id={self.chatroom_id})')

        names = [
            'LUCAS_KICK', 'FLAVIA_PLAY', 'KICKFAN_22', 'MARCOS_SUB', 'CAMILA_VIP',
            'BRENO_FIRE', 'TIAGO_GAMER', 'NINA_LIVE', 'RAFA_STREAM', 'GABI_NIGHT',
        ]
        msgs = [
            'kkkk esse jogo tá insano', 'salve galera!', 'bora mais uma partida',
            'glória a deus!', 'fazendo a call aqui', 'esse mapa é muito ruim',
            'kkkkk que isso', 'salve mod!', 'aooo', 'top demais',
        ]
        import random
        i = 0
        while self._should_run:
            # Mensagem a cada 4-10s pra não spammar
            await asyncio.sleep(random.uniform(4, 10))
            if not self._should_run:
                break
            n = random.choice(names)
            m = random.choice(msgs)
            msg = KickMessage(
                username=n.lower(),
                display_name=n,
                user_id=str(1000 + i),
                color='#ffffff',
                message=m,
                is_sub=random.random() > 0.7,
                is_vip=random.random() > 0.85,
                is_mod=False,
            )
            if self._on_message:
                try:
                    await self._on_message(msg)
                except Exception as e:
                    logger.error(f'callback erro: {e!r}')
            i += 1

    async def _fetch_chatroom_id(self) -> None:
        """Busca chatroom_id do canal na API pública do Kick.

        A API /api/v1/channels/<slug> ainda é pública e não precisa de auth.
        Retorna JSON com campo "chatroom.id".
        """
        if not self._client:
            self._client = httpx.AsyncClient(
                headers={'User-Agent': 'SorteadorGeral/0.1', 'Accept': 'application/json'},
                timeout=httpx.Timeout(10.0),
            )
        url = f'https://kick.com/api/v1/channels/{self.channel}'
        resp = await self._client.get(url)
        if resp.status_code != 200:
            raise ValueError(f'A Kick recusou identificar a sala (HTTP {resp.status_code}). Informe o ID da sala em Opções avançadas ou use Webhooks.')
        data = resp.json()
        chatroom = data.get('chatroom') or {}
        self.chatroom_id = int(chatroom['id']) if chatroom.get('id') else None
        self.channel_id = int(data['id']) if data.get('id') else self.channel_id
        self.broadcaster_user_id = str(data.get('user_id') or (data.get('user') or {}).get('id') or '')

    @property
    def is_connected(self) -> bool:
        return self.connected

    async def send_message(self, text: str) -> bool:
        """API pública oficial; confirma is_sent e renova token expirado."""
        from .kick_oauth import get_oauth
        from .state import STATE
        self.last_send_error = ''
        self.last_sent_message_id = ''
        try:
            oauth = get_oauth()
            valid, token = await oauth.ensure_valid_token()
            if not valid or not oauth.has_chat_write():
                self.last_send_error = 'Envio requer uma conta autorizada na Kick com token válido e chat:write. Autorize novamente se o token venceu.'
                logger.warning('Kick: envio requer OAuth válido com chat:write')
                return False
            channel = oauth.get_channel_info()
            target_slug = self.channel or STATE.kick_channel
            if not text.strip() or len(text) > 500 or len(text.encode('utf-8')) > 2048:
                return False
            async with httpx.AsyncClient(timeout=10) as client:
                if target_slug and (not channel or target_slug.casefold() != channel.slug.casefold()):
                    if not self.broadcaster_user_id:
                        lookup = await client.get('https://api.kick.com/public/v1/channels',
                            headers={'Authorization':f'Bearer {token}'},params={'slug':target_slug})
                        if lookup.status_code != 200:
                            self.last_send_error = f'Não foi possível identificar o canal de destino (HTTP {lookup.status_code}). Confira channel:read e o nome do canal.'
                            return False
                        candidates = lookup.json().get('data') or []
                        target = next((item for item in candidates if str(item.get('slug','')).casefold() == target_slug.casefold()),None)
                        if not target:
                            self.last_send_error = 'Canal de destino não encontrado na API da Kick.'
                            return False
                        self.broadcaster_user_id = str(target['broadcaster_user_id'])
                    broadcaster = int(self.broadcaster_user_id)
                elif channel:
                    broadcaster = int(channel.broadcaster_user_id)
                else:
                    self.last_send_error = 'O canal da conta autorizada não foi identificado. Autorize novamente com channel:read.'
                    return False
                response = await client.post('https://api.kick.com/public/v1/chat',
                    headers={'Authorization': f'Bearer {token}'},
                    json={'type': 'user', 'broadcaster_user_id': broadcaster, 'content': text})
            if response.status_code not in (200, 201):
                self.last_send_error = f'A Kick recusou o envio (HTTP {response.status_code}). Confira chat:write, a conta e as restrições do chat.'
                logger.warning('Kick: envio recusado (HTTP %s)', response.status_code)
                return False
            data = response.json().get('data') or {}
            if isinstance(data, list):
                data = data[0] if data else {}
            sent = data.get('is_sent') is True
            if sent:self.last_sent_message_id=str(data.get('message_id') or '')
            if not sent:self.last_send_error = 'A Kick recebeu a solicitação, mas não confirmou is_sent. Confira as restrições do chat.'
            return sent
        except Exception:
            self.last_send_error = 'Falha de comunicação ao enviar para a Kick. Confira o diagnóstico e tente novamente.'
            logger.exception('Kick: falha ao enviar mensagem')
            return False

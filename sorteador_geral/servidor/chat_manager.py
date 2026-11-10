"""Gerenciador unificado de chats: Twitch + Kick.

Mantém:
- Instâncias TwitchChat e KickChat
- Lista de participantes (deduplicada por plataforma+username)
- Métodos pra conectar/desconectar
- Callbacks que adicionam participantes e atualizam STATE

Os callbacks disparam: on_participant_change(state) pra notificar o WebSocket manager.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from typing import Callable, Awaitable

from . import antibot, db, megamu
from . import twitch_api
from .state import Participant, STATE, add_participant, log, participant_weight, format_weight
from .twitch_chat import TwitchChat, TwitchMessage
from .kick_chat import KickChat, KickMessage

logger = logging.getLogger(__name__)


class ChatManager:
    def __init__(self, on_change: Callable[[], Awaitable[None]] | None = None):
        self.on_chat_message = None
        self._on_change = on_change  # notifica mudança pra broadcastar via WS
        self.last_send_errors = {}
        self._announcements = set()
        self._claim_cleanup_task = None
        self._outgoing = []
        self._seen_messages = {}
        self._captcha_feedback_at = {}
        self._skip_refusal_at = {}
        self._nick_request_at = {}
        self._nick_global_at = -100.0
        self._rank_request_at = {}
        self._rank_global_at = -100.0

        self.twitch = TwitchChat()
        self.kick = KickChat()
        self.twitch.set_callback(self._on_twitch)
        self.kick.set_callback(self._on_kick)

    # ===== Notificação =====
    async def _notify(self) -> None:
        if self._on_change:
            try:
                await self._on_change()
            except Exception as e:
                logger.error(f'on_change erro: {e!r}')

    async def _record_chat(self, msg, *, winner_eligible: bool = True) -> None:
        message_id = getattr(msg, 'message_id', '') or uuid.uuid4().hex
        if any(m['id'] == message_id and m['platform'] == msg.platform for m in STATE.chat_messages):
            return
        channel = getattr(msg, 'channel', '') or getattr(STATE, f'{msg.platform}_channel', '') or getattr(self, msg.platform).channel
        source = getattr(msg, 'source_channel', '') or channel
        item = {'id': message_id, 'platform': msg.platform, 'username': msg.username,
                'display_name': msg.display_name or msg.username, 'text': msg.message,
                'user_id': str(getattr(msg,'user_id','') or ''),
                'channel': channel, 'source_channel': source,
                'shared': bool(getattr(msg, 'source_broadcaster_id', '')) or source.casefold() != channel.casefold(),
                'mentions': getattr(msg, 'mentions', None) or [],
                'color': msg.color, 'ts': time.time()}
        STATE.chat_messages.append(item)
        # Após confirmar o prêmio, mantém o cartão do vencedor enquanto ele
        # informa o personagem. Nunca recupera um vencedor antigo/expirado.
        winner=(STATE.current_winner or STATE.winner_claim_pending) if STATE.is_running else None
        if winner_eligible and winner and winner.platform==msg.platform:
            same_user=(str(winner.user_id)==str(msg.user_id) if winner.user_id and msg.user_id
                else winner.username.casefold()==msg.username.strip().casefold())
            if same_user and item['ts']>=winner.drawn_at:
                item['winner_drawn_at']=winner.drawn_at
                STATE.winner_chat_messages.append(dict(item))
                await self._notify()
        if self.on_chat_message:
            await self.on_chat_message(item)

    def _ignore_message(self, msg):
        now=time.monotonic()
        self._seen_messages={key:at for key,at in self._seen_messages.items() if now-at<300}
        mid=getattr(msg,'message_id','')
        key=(msg.platform,mid)
        if mid and key in self._seen_messages:return True
        if mid:self._seen_messages[key]=now
        self._outgoing=[entry for entry in self._outgoing if now-entry['at']<120]
        for entry in self._outgoing:
            if entry['platform']!=msg.platform:continue
            if mid and mid==entry.get('id'):return True
            if (entry['sender'] and str(msg.user_id)==entry['sender'] and
                    msg.message.strip()==entry['text']):return True
        return False

    # ===== Twitch =====
    async def connect_twitch(self, channel: str, client_id: str = '', token: str = '') -> None:
        """Conecta ao chat via EventSub WebSocket.
        client_id e token vêm de STATE.bot_twitch_client_id / bot_twitch_oauth
        (mesmas credenciais Helix já configuradas)."""
        if not client_id:
            client_id = STATE.bot_twitch_client_id
        if not token:
            token = STATE.bot_twitch_oauth
        # limpa prefixo oauth: se vier
        if token and token.startswith('oauth:'):
            token = token[len('oauth:'):]
        await self.twitch.connect(channel, client_id=client_id, token=token)
        logger.info(f'ChatManager: Twitch conectado em #{channel}')

    async def disconnect_twitch(self) -> None:
        await self.twitch.disconnect()
        logger.info('ChatManager: Twitch desconectado')

    async def _on_twitch(self, msg: TwitchMessage) -> None:
        ignored=self._ignore_message(msg)
        await self._record_chat(msg,winner_eligible=not ignored)
        if ignored:return
        if await self._handle_viewer_command(msg):
            return
        if await self._handle_winner_reply(msg):
            return
        # === !roleta: mostrar/ocultar overlay ===
        m = msg.message.strip()
        if m.split(maxsplit=1)[0:1] == ['!roleta'] or m.lower().split(maxsplit=1)[0:1] == ['!roleta']:
            if getattr(msg, 'source_broadcaster_id', ''):
                return
            if not (msg.is_mod or msg.is_owner or msg.is_broadcaster):
                return
            parts = m.split()
            if len(parts) == 1 or parts[1].lower() in ('mostrar', 'show', 'on'):
                await self._set_roleta_visible(True, msg.username)
            elif parts[1].lower() in ('ocultar', 'hide', 'off'):
                await self._set_roleta_visible(False, msg.username)
            return  # comando processado, não é participação de sorteio

        # Se sorteio tá rodando, registra participação quando keyword bate
        if not STATE.is_running or STATE.is_paused:
            return
        if not getattr(STATE, f'entry_open_{msg.platform}', False):
            return
        keyword = STATE.keyword.strip().lower()
        if not keyword:
            return
        if msg.message.strip().lower() != keyword:
            return

        added = self._add_participant(
            platform='twitch',
            username=msg.username,
            user_id=msg.user_id,
            is_sub=msg.is_sub,
            is_vip=msg.is_vip,
            is_mod=msg.is_mod,
            is_owner=msg.is_owner,
        )
        await self._announce_entry(msg.platform, msg.username, added)
        if added:
            logger.info(f'Participante adicionado (Twitch): {msg.username}')
            # Se tiver credencial Twitch configurada, busca avatar (async, fire-and-forget)
            if msg.user_id:
                asyncio.create_task(self._fetch_and_set_avatar('twitch', msg.username, msg.user_id))
            await self._notify()

    async def _handle_winner_reply(self, msg) -> bool:
        from .giveaway import giveaway
        winner = STATE.current_winner
        if not STATE.is_running or winner is None or winner.platform != msg.platform:
            return False
        same_user = (str(winner.user_id) == str(msg.user_id) if winner.user_id and msg.user_id
                     else winner.username.strip().casefold() == msg.username.strip().casefold())
        if not same_user or not msg.message.strip():
            return False
        if STATE.draw_reveal_until > time.time():
            return True  # resposta só vale após a revelação e anúncio do vencedor
        if STATE.winner_deadline and time.time() >= STATE.winner_deadline:
            return True  # uma resposta atrasada não revive o cronômetro
        if winner.captcha_required and not winner.presence_confirmed:
            # A primeira fala confirma presença; não pode ser uma tentativa de
            # resolver um código que ainda não foi exibido.
            await giveaway.confirm_presence()
            if STATE.captcha_send_to_chat and STATE.antibot_challenge:
                self._schedule_announcement('captcha_challenge', platform=msg.platform,
                    nome=winner.username, desafio=STATE.antibot_challenge['question'])
            await self._notify()
            return True
        if winner.captcha_required and winner.captcha_failed and not STATE.antibot_challenge:
            return True  # aguarda decisão do administrador
        if STATE.antibot_challenge:
            result = await giveaway.submit_captcha(msg.message)
            if result['status'] == 'expired':
                await self._notify()
            elif not result['ok']:
                if result.get('exhausted'):
                    log(f'{msg.username}: tentativas de captcha esgotadas; aguardando administrador.', 'warning')
                    self._schedule_announcement('captcha_fail', platform=msg.platform,
                        nome=winner.username, resposta=result['expected'])
                else:
                    self._schedule_announcement('captcha_retry',platform=msg.platform,
                        nome=winner.username,tentativa=result['attempts'],
                        limite=result['max_attempts'] or '∞',
                        restantes=result['remaining'] if result['remaining'] is not None else '∞')
        else:
            await giveaway.answer()
        return True

    async def _handle_viewer_command(self, msg) -> bool:
        """Processa comandos antes da resposta comum do vencedor.

        Isso impede que !pular ou !nick confirmem acidentalmente um prêmio.
        """
        message = msg.message.strip()
        if not message or not message.startswith('!'):
            return False
        command = message.split(maxsplit=1)[0].casefold()
        if command == STATE.skip_chat_command.casefold():
            await self._voluntary_skip(msg)
            return True
        if command == STATE.nick_lookup_command.casefold():
            await self._nick_lookup(msg, message)
            return True
        # Para o vencedor que está aguardando o prêmio, também aceitar
        # !NomeDoPersonagem (sem a palavra literal "nick"). Não interceptar
        # a palavra-chave do sorteio nem comandos reservados.
        claim = STATE.winner_claim_pending
        reserved = {STATE.keyword.casefold(), STATE.skip_chat_command.casefold(),
                    STATE.rank_lookup_command.casefold(), '!roleta'}
        same_claim_user = bool(claim and claim.platform == msg.platform and (
            str(claim.user_id) == str(msg.user_id) if claim.user_id and msg.user_id
            else claim.username.casefold() == msg.username.strip().casefold()))
        if (same_claim_user and command not in reserved and not message.split(maxsplit=1)[1:]
                and re.fullmatch(r'![A-Za-z0-9_-]{2,24}', message)):
            await self._nick_lookup(msg, STATE.nick_lookup_command + ' ' + message[1:])
            return True
        if command == STATE.rank_lookup_command.casefold():
            await self._rank_lookup(msg, message)
            return True
        return False

    async def _voluntary_skip(self, msg) -> None:
        from .giveaway import giveaway
        winner = STATE.current_winner
        if not STATE.skip_chat_enabled or not STATE.is_running or winner is None:
            return
        if msg.platform != winner.platform:
            return
        same_user = (str(winner.user_id) == str(msg.user_id) if winner.user_id and msg.user_id
                     else winner.username.casefold() == msg.username.strip().casefold())
        if not same_user or STATE.draw_reveal_until > time.time() or (STATE.winner_deadline and time.time() >= STATE.winner_deadline):
            return
        if STATE.skip_chat_uses >= STATE.skip_chat_limit:
            feedback_key = (winner.platform, winner.username, winner.drawn_at)
            now = time.monotonic()
            if now - self._skip_refusal_at.get(feedback_key, -100) > 10:
                self._skip_refusal_at[feedback_key] = now
                self._schedule_announcement('winner_skip_limit', platform=winner.platform,
                    nome=winner.username, limite=STATE.skip_chat_limit,
                    comando=STATE.skip_chat_command, usos=STATE.skip_chat_uses)
            return
        # O contador é consumido antes do primeiro await. Mensagens duplicadas
        # não podem fazer outro vencedor desistir no lugar do anterior.
        STATE.skip_chat_uses += 1
        uses = STATE.skip_chat_uses
        log(f'⏭️ {winner.username} desistiu pelo comando {STATE.skip_chat_command}.')
        self._schedule_announcement('winner_declined', platform=winner.platform,
            nome=winner.username, limite=STATE.skip_chat_limit,
            comando=STATE.skip_chat_command, usos=uses)
        await giveaway.skip(reason='chat_voluntary')

    async def _nick_lookup(self, msg, message: str) -> None:
        if not STATE.nick_lookup_enabled:
            return
        parts = message.split(maxsplit=1)
        nick = parts[1].strip() if len(parts) > 1 else ''
        if not nick:
            if STATE.winner_claim_pending and STATE.winner_claim_pending.username.casefold() == msg.username.casefold():
                STATE.winner_claim_feedback = {'status':'error','nick':'',
                    'result':f'Informe o personagem: {STATE.nick_lookup_command} NomeDoPersonagem ou !NomeDoPersonagem.'}
                await self._notify()
            self._schedule_announcement('nick_lookup_error', platform=msg.platform,
                nome=msg.username, motivo=f'Use {STATE.nick_lookup_command} NomeDoPersonagem.')
            return
        # Só o vencedor da plataforma certa pode concluir a etapa pendente.
        claim = STATE.winner_claim_pending
        if claim and claim.platform == msg.platform:
            same_user = (str(claim.user_id) == str(msg.user_id) if claim.user_id and msg.user_id
                         else claim.username.casefold() == msg.username.strip().casefold())
            if not same_user:
                claim = None
        else:
            claim = None
        # A solicitação do vencedor não pode ser bloqueada por outro usuário
        # que usou !nick instantes antes. Retentativas dele têm pausa de 2 s.
        now = time.monotonic()
        user_key = (msg.platform, msg.username.casefold())
        last_user = self._nick_request_at.get(user_key, -100)
        if claim:
            if now - last_user < 2:
                STATE.winner_claim_feedback={'status':'waiting','nick':nick,
                    'result':'Aguarde 2 segundos para consultar outro personagem.'}
                await self._notify()
                return
        elif now - last_user < 15 or now - self._nick_global_at < 3:
            return
        self._nick_request_at[user_key] = now
        self._nick_global_at = now
        if len(self._announcements) >= 80:
            if claim:
                STATE.winner_claim_feedback={'status':'error','nick':nick,
                    'result':'Sistema ocupado. Tente novamente em instantes.'}
                await self._notify()
            return
        feedback = None
        if claim:
            feedback={'status':'checking','nick':nick,
                      'result':'Consultando o personagem no MEGAMU...'}
            STATE.winner_claim_feedback=feedback
        task = asyncio.create_task(self._answer_nick_lookup(msg.platform, msg.username, nick, claim, feedback))
        self._announcements.add(task)
        task.add_done_callback(self._announcements.discard)
        if feedback:
            await self._notify()

    async def _answer_nick_lookup(self, platform: str, username: str, nick: str, claim=None, feedback=None) -> None:
        try:
            result = await megamu.character_info(nick)
        except ValueError as error:
            if claim is not None and STATE.winner_claim_pending is claim and STATE.winner_claim_feedback is feedback:
                feedback.update(status='error',result=str(error))
                await self._notify()
            sent=await self.announce('nick_lookup_error', platform=platform,
                nome=username, nick=nick, motivo=str(error))
            await self._record_nick_delivery(platform,feedback,sent)
        except Exception:
            logger.exception('Falha inesperada ao consultar personagem MEGAMU')
            reason='Não foi possível consultar o MEGAMU agora. Tente novamente.'
            if claim is not None and STATE.winner_claim_pending is claim and STATE.winner_claim_feedback is feedback:
                feedback.update(status='error',result=reason)
                await self._notify()
            sent=await self.announce('nick_lookup_error', platform=platform,
                nome=username, nick=nick, motivo=reason)
            await self._record_nick_delivery(platform,feedback,sent)
        else:
            if claim is not None and STATE.winner_claim_pending is claim and STATE.winner_claim_feedback is feedback:
                feedback.update(status='success',result=result)
                STATE.winner_claim_recent = claim
                STATE.winner_claim_feedback_until = time.time() + 12
                STATE.winner_claim_pending = None
                STATE.status_message = f'✅ {username} informou o personagem {nick}. Pronto para o próximo sorteio.'
                await db.audit_add('chat', 'winner_claim_nick', {
                    'username':claim.username, 'platform':claim.platform,
                    'nick':nick, 'award':claim.award, 'drawn_at':claim.drawn_at})
                await self._notify()
                if self._claim_cleanup_task and not self._claim_cleanup_task.done():
                    self._claim_cleanup_task.cancel()
                self._claim_cleanup_task=asyncio.create_task(self._clear_claim_feedback(feedback))
            result_send=await self.announce('nick_lookup', platform=platform,
                nome=username, nick=nick, resultado=result)
            await self._record_nick_delivery(platform,feedback,result_send)

    async def _record_nick_delivery(self, platform, feedback, delivery) -> None:
        if feedback is not None and STATE.winner_claim_feedback is feedback:
            status=delivery.get(platform,{}) if isinstance(delivery,dict) else {}
            feedback.update(chat_sent=bool(status.get('sent')),
                            chat_reason=status.get('reason',''))
            await self._notify()

    async def _clear_claim_feedback(self, feedback) -> None:
        await asyncio.sleep(12)
        if STATE.winner_claim_feedback is feedback:
            STATE.winner_claim_feedback = None
            STATE.winner_claim_recent = None
            STATE.winner_claim_feedback_until = 0.0
            await self._notify()

    async def _rank_lookup(self, msg, message: str) -> None:
        if not STATE.rank_lookup_enabled:
            return
        parts = message.split(maxsplit=1)
        nick = (parts[1].strip().lstrip('@') if len(parts) > 1 else msg.username.strip())
        # Busca por usuário da mesma plataforma, independentemente da coleta.
        if not re.fullmatch(r'[\w.-]{1,40}', nick, re.UNICODE):
            return
        now = time.monotonic()
        key = (msg.platform, msg.username.casefold())
        if now - self._rank_request_at.get(key, -100) < 10 or now - self._rank_global_at < 2:
            return
        self._rank_request_at[key] = now
        self._rank_global_at = now
        if len(self._announcements) >= 80:
            return
        task = asyncio.create_task(self._answer_rank_lookup(msg.platform, msg.username, nick))
        self._announcements.add(task)
        task.add_done_callback(self._announcements.discard)

    async def _answer_rank_lookup(self, platform: str, username: str, nick: str) -> None:
        try:
            stats = await db.winner_rank(platform, nick)
        except Exception:
            logger.exception('Não foi possível consultar histórico do !rank')
            return
        await self.announce('rank_lookup', platform=platform, nome=username, nick=nick, **stats)

    async def _announce_entry(self, platform: str, username: str, added: bool):
        from .giveaway import giveaway
        chance = next((p['chance_pct'] for p in giveaway.compute_chances()
            if p['platform'] == platform and p['username'].casefold() == username.casefold()), 0)
        participant=STATE.participants.get(platform+':'+username.strip().lower())
        if participant and not participant.active:
            return  # digitar a palavra-chave outra vez não reativa uma exclusão manual
        if participant and (participant.is_winner or (STATE.block_repeat_winner and
                any(w.username.casefold()==username.strip().casefold() for w in STATE.winners))):return
        self._schedule_announcement('entry_accepted' if added else 'entry_repeat', platform=platform,
            nome=username, chance=f'{chance:.2f}', participantes=len(STATE.participants),
            peso=format_weight(participant.weight if participant else 1),
            plataforma=platform)

    def _schedule_announcement(self,event,**values):
        # O envio não bloqueia a leitura de novas respostas/captchas do chat.
        if len(self._announcements) >= 80:
            log('Fila de mensagens cheia. A leitura e as inscrições continuam ativas.', 'warning')
            return
        task=asyncio.create_task(self.announce(event,**values))
        self._announcements.add(task)
        task.add_done_callback(self._announcements.discard)

    def _schedule_ordered_announcements(self, entries):
        """Envia eventos sequenciais sem bloquear a leitura do chat."""
        if len(self._announcements) >= 80:
            log('Fila de mensagens cheia. Não foi possível agendar a confirmação.', 'warning')
            return
        async def deliver():
            for event, values in entries:
                await self.announce(event, **values)
        task = asyncio.create_task(deliver())
        self._announcements.add(task)
        task.add_done_callback(self._announcements.discard)

    async def _on_captcha_correct(self) -> None:
        """Callback quando vencedor acerta o captcha (via chat)."""
        from .giveaway import giveaway
        await giveaway.answer()
        await self._notify()

    async def _set_roleta_visible(self, visible: bool, username: str) -> None:
        """Mostra ou oculta o overlay da roleta via chat."""
        from .roleta import set_visible
        await set_visible(visible)
        await db.audit_add('chat', 'roleta_visible', {
            'username': username, 'visible': visible,
        })
        logger.info(f'Roleta overlay {"mostrado" if visible else "ocultado"} por {username}')
        await self._notify()

    async def _fetch_and_set_avatar(self, platform: str, username: str, user_id: str) -> None:
        """Busca avatar via API da plataforma e atualiza o participante. Fire-and-forget."""
        url = ''
        if platform == 'twitch':
            url = await twitch_api.get_avatar(user_id)
        # Kick: sem API pública simples; deixar vazio
        if not url:
            return
        # atualiza o participant se ainda estiver no state
        key = f'{platform}:{username.lower()}'
        p = STATE.participants.get(key)
        if p and not p.avatar_url:
            p.avatar_url = url
            logger.debug(f'Avatar setado pra {username}: {url[:60]}')
            await self._notify()

    # ===== Kick =====
    async def connect_kick(
        self,
        channel: str = '',
        simulate: bool = True,
        oauth_status_check: bool = True,
        mode: str = 'direct',
        chatroom_id: int | None = None,
        channel_id: int | None = None,
    ) -> tuple[bool, str]:
        """Conecta ao chat Kick.

        Args:
            channel: Canal a conectar (opcional, usa OAuth se disponível)
            simulate: Modo simulação (padrão True)
            oauth_status_check: Verificar status OAuth antes de conectar

        Returns:
            (success, message)
        """
        # Se não passou canal, tenta obter do OAuth
        if not channel:
            try:
                from .kick_chat_auth import get_kick_auth
                auth = get_kick_auth()
                has_channel, oauth_channel = auth.get_required_channel()
                if has_channel:
                    channel = oauth_channel
            except Exception:
                pass

        # Verifica status OAuth se não for simulação
        if not simulate and oauth_status_check and mode == 'webhook':
            try:
                from .kick_chat_auth import get_kick_auth
                auth = get_kick_auth()
                status = auth.get_status()

                if not status.is_authenticated:
                    return False, f'OAuth não autenticado: {status.message}'

                if not status.is_channel_identified:
                    return False, f'Canal não identificado: {status.message}'

                if not status.has_required_scopes:
                    return False, f'Escopos insuficientes: {status.missing_scopes}'

                # Avisa sobre events:subscribe ausente
                if not status.has_events_subscribe:
                    logger.warning('Kick: escopo events:subscribe ausente, webhooks não funcionarão')

            except Exception as e:
                logger.warning(f'Kick: erro ao verificar OAuth: {e!r}')

        try:
            options = {'simulate': simulate, 'mode': mode, 'chatroom_id': chatroom_id}
            if channel_id:
                options['channel_id'] = channel_id
            await self.kick.connect(channel, **options)
            logger.info(f'ChatManager: Kick conectado em @{channel} (simulate={simulate})')
            return True, ''
        except NotImplementedError as e:
            logger.warning(f'Kick: conexão real não implementada — {e}')
            return False, str(e)
        except Exception as e:
            logger.error(f'Kick: erro ao conectar — {e!r}')
            return False, str(e)

    async def disconnect_kick(self) -> None:
        await self.kick.disconnect()
        logger.info('ChatManager: Kick desconectado')

    async def _on_kick(self, msg: KickMessage) -> None:
        ignored=self._ignore_message(msg)
        await self._record_chat(msg,winner_eligible=not ignored)
        if ignored:return
        if await self._handle_viewer_command(msg):
            return
        if await self._handle_winner_reply(msg):
            return
        # === !roleta: mostrar/ocultar overlay ===
        m = msg.message.strip()
        if m.split(maxsplit=1)[0:1] == ['!roleta'] or m.lower().split(maxsplit=1)[0:1] == ['!roleta']:
            if getattr(msg, 'source_broadcaster_id', ''):
                return
            if not (msg.is_mod or msg.is_owner or msg.is_broadcaster):
                return
            parts = m.split()
            if len(parts) == 1 or parts[1].lower() in ('mostrar', 'show', 'on'):
                await self._set_roleta_visible(True, msg.username)
            elif parts[1].lower() in ('ocultar', 'hide', 'off'):
                await self._set_roleta_visible(False, msg.username)
            return  # comando processado, não é participação de sorteio

        if not STATE.is_running or STATE.is_paused:
            return
        if not getattr(STATE, f'entry_open_{msg.platform}', False):
            return
        keyword = STATE.keyword.strip().lower()
        if not keyword:
            return
        if msg.message.strip().lower() != keyword:
            return

        added = self._add_participant(
            platform='kick',
            username=msg.username,
            user_id=msg.user_id,
            is_sub=msg.is_sub,
            is_vip=msg.is_vip,
            is_mod=msg.is_mod,
            is_owner=msg.is_owner,
        )
        await self._announce_entry(msg.platform, msg.username, added)
        if added:
            logger.info(f'Participante adicionado (Kick): {msg.username}')
            await self._notify()

    # ===== Lógica de participante =====
    def _add_participant(
        self,
        platform: str,
        username: str,
        user_id: str,
        is_sub: bool,
        is_vip: bool,
        is_mod: bool,
        is_owner: bool,
    ) -> bool:
        """Adiciona participante se elegível. Retorna True se foi adicionado."""
        username_l = username.strip().lower()
        if not username_l:
            return False
        # O dono do canal segue a mesma permissão de participação dos moderadores.
        # Ser dono não significa ser um bot.
        is_mod = is_mod or is_owner

        # A maior chance entre as categorias, sem somar bônus.
        weight = participant_weight(platform,is_sub,is_vip,is_mod or is_owner)

        return add_participant(
            platform=platform,
            username=username,
            user_id=user_id,
            is_sub=is_sub,
            is_vip=is_vip,
            is_mod=is_mod,
            is_owner=is_owner,
            weight=weight,
        )

    # ===== State queries =====
    @property
    def twitch_connected(self) -> bool:
        return self.twitch.is_connected

    @property
    def kick_connected(self) -> bool:
        return self.kick.is_connected

    @property
    def twitch_channel(self) -> str:
        return self.twitch.channel

    @property
    def kick_channel(self) -> str:
        return self.kick.channel

    @property
    def twitch_can_send(self) -> bool:
        """Verifica se a Twitch pode enviar mensagens."""
        return self.twitch.can_send_messages

    async def send(self, platform: str, text: str, *, automatic: bool = True) -> bool:
        """Envia mensagem no chat da plataforma. Retorna True se enviou.

        - Twitch: precisa de oauth token com user:write:chat configurado.
        - Kick: API pública, OAuth com chat:write.

        Returns:
            True se a mensagem foi enviada com sucesso, False caso contrário.
        """
        if automatic and not getattr(STATE, f'bot_{platform}_enabled', False):
            return False
        if STATE.simulation_mode:
            return False
        sender=str(self.twitch.user_id or '') if platform=='twitch' else ''
        if platform=='kick':
            from .kick_oauth import get_oauth
            try: sender=str(get_oauth().get_user_info()[0] or '')
            except RuntimeError: pass
        marker={'platform':platform,'sender':sender,'text':text.strip(),'at':time.monotonic()}
        self._outgoing.append(marker)
        self._outgoing=self._outgoing[-500:]
        if platform == 'twitch':
            result = await self.twitch.send_message(text)
            marker['id']=result.get('message_id','')
            if not result['success']:self._outgoing.remove(marker)
            self.last_send_errors[platform] = result.get('error') or ''
            if not result['success']:
                if result['no_permission']:
                    logger.warning('Twitch: sem permissão para enviar mensagens (verifique o token)')
                elif result['rate_limited']:
                    logger.warning('Twitch: rate limit atingido')
                elif result['error']:
                    logger.warning(f'Twitch: falha ao enviar: {result["error"]}')
            return result['success']
        if platform == 'kick':
            sent = await self.kick.send_message(text)
            marker['id']=getattr(self.kick,'last_sent_message_id','')
            if not sent:self._outgoing.remove(marker)
            self.last_send_errors[platform] = self.kick.last_send_error
            return sent
        return False

    async def announce(self, event: str, platform: str = '', **values) -> dict:
        """Confirma o resultado por plataforma, inclusive quando o envio está desligado."""
        values = {'keyword': STATE.keyword, 'tempo': STATE.winner_timer_seconds,
                  'nome': '', 'premio': '', 'plataforma': '', 'desafio':'', 'resposta':'',
                  'chance':'0.00','peso':'1','participantes':len(STATE.participants),'proximo':'',
                  'tentativa':0,'restantes':0,
                  'comando':STATE.skip_chat_command,'comando_nick':STATE.nick_lookup_command,
                  'usos':STATE.skip_chat_uses,
                  'limite':STATE.skip_chat_limit,'nick':'','resultado':'','motivo':'',
                  'total':0,'respondeu':0,'mamou':0,'desistiu':0,'pulou':0,'pendente':0,
                  **values}
        async def deliver(target):
            template = STATE.message_templates.get(event, {}).get(target, '')
            if not STATE.chat_event_platforms.get(event,{}).get(target,True):
                return target, {'sent':False,'reason':'Evento silenciado nesta plataforma na aba Mensagens.'}
            if not STATE.chat_events.get(event, False):
                return target, {'sent': False, 'reason': 'Anúncio deste evento desligado na aba Mensagens.'}
            if not getattr(STATE, f'bot_{target}_enabled', False):
                return target, {'sent': False, 'reason': 'Envio automático desligado na conexão desta plataforma.'}
            if STATE.simulation_mode:
                return target, {'sent': False, 'reason': 'Modo simulação ativo. Conecte o chat real.'}
            if not template:
                return target, {'sent': False, 'reason': 'Texto do anúncio vazio.'}
            try:
                text = template.format_map(values)
                # Compatibilidade: modelos já salvos no banco podem ser da
                # versão antiga, sem {resposta}. Ainda assim informamos a
                # solução quando a única tentativa de captcha é incorreta.
                if event == 'captcha_fail' and values.get('resposta') and '{resposta}' not in template:
                    text += f' A resposta correta era: {values["resposta"]}.'
                sent = await asyncio.wait_for(self.send(target, text), timeout=25)
                reason = '' if sent else self.last_send_errors.get(target) or 'A plataforma não confirmou o envio. Confira a conexão e a permissão de escrita.'
                await db.audit_add('system', 'chat_announcement', {
                    'platform': target, 'event': event, 'sent': sent})
                if not sent:
                    log(f'{target.title()}: anúncio {event} não enviado. {reason}', 'warning')
                return target, {'sent': sent, 'reason': reason}
            except Exception:
                logger.exception('Falha no anúncio %s (%s)', event, target)
                reason = 'Falha ao enviar o anúncio. Confira a conexão, o token e o modelo da mensagem.'
                log(f'{target.title()}: {reason}', 'warning')
                return target, {'sent': False, 'reason': reason}
        return dict(await asyncio.gather(*(deliver(target) for target in
                    ([platform] if platform else ['twitch', 'kick']))))

    async def shutdown(self) -> None:
        if self._claim_cleanup_task and not self._claim_cleanup_task.done():
            self._claim_cleanup_task.cancel()
            await asyncio.gather(self._claim_cleanup_task, return_exceptions=True)
        for task in self._announcements:task.cancel()
        if self._announcements:await asyncio.gather(*self._announcements,return_exceptions=True)
        await self.twitch.disconnect()
        await self.kick.disconnect()

    # ===== Kick Webhook Integration =====
    def handle_kick_webhook_event(self, event) -> bool:
        """Processa evento de webhook do Kick.

        Converte o KickWebhookEvent para KickMessage e encaminha ao
        processamento de participantes.

        Args:
            event: KickWebhookEvent validado

        Returns:
            True se o evento foi processado (mesmo que não tenha gerado participante)
            False se o evento não era chat.message.sent
        """
        from .kick_chat import KickMessage

        if STATE.kick_receive_mode != 'webhook' or not STATE.kick_receive_enabled:
            return False
        if event.event_type != 'chat.message.sent':
            return False

        # Extrai badges do sender.identity se disponível
        badges = []
        sender_identity = event.payload.get('sender', {}).get('identity') or {}
        if isinstance(sender_identity, dict):
            badges = sender_identity.get('badges') or []

        # Extrai badges do payload (formato alternativo)
        if not badges and event.payload.get('sender', {}).get('badges'):
            badges = event.payload.get('sender', {}).get('badges')

        # Converte badges para flags
        badge_types = {b.get('type', '').lower() if isinstance(b, dict) else str(b).lower() for b in badges}

        msg = KickMessage(
            platform='kick',
            message_id=event.message_id,
            username=event.sender_username,
            display_name=event.sender_username,
            user_id=event.sender_user_id,
            color='#ffffff',
            message=event.message_content,
            is_sub='subscriber' in badge_types or 'founder' in badge_types,
            is_vip='vip' in badge_types,
            is_mod='moderator' in badge_types,
            is_owner='broadcaster' in badge_types,
            is_broadcaster='broadcaster' in badge_types,
            badges=[b.get('type', '') if isinstance(b, dict) else str(b) for b in badges],
        )

        logger.debug(
            f'Kick webhook → msg: user={msg.username}, '
            f'user_id={msg.user_id}, content={msg.message[:30]}...'
        )

        # Executa o callback de mensagem (mesmo código de _on_kick)
        # cria uma task assíncrona
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._on_kick(msg))
        except RuntimeError:
            # Sem loop rodando, cria novo
            asyncio.create_task(self._on_kick(msg))
        return True


# Instância global
_chat_manager: ChatManager | None = None


def get_chat_manager() -> ChatManager:
    """Retorna instância global do ChatManager.

    A instância deve ser criada pelo app.py e configurada antes de ser usada.
    """
    global _chat_manager
    if _chat_manager is None:
        _chat_manager = ChatManager()
    return _chat_manager


def set_chat_manager(manager: ChatManager) -> None:
    """Define a instância global do ChatManager.

    Deve ser chamado pelo app.py após criar a instância.
    """
    global _chat_manager
    _chat_manager = manager

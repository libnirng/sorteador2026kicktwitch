"""Servidor principal do Sorteador Geral.

Etapa 1: esqueleto funcional
- Servidor HTTP + WebSocket em 127.0.0.1:8765
- Carrega config do SQLite no startup
- Salva config no shutdown
- Mantém o estado global acessível via API

Os módulos de cada feature (sorteio, anti-bot, roleta, bots, chats) serão
adicionados nas próximas etapas. Por enquanto o servidor só sabe servir
os arquivos estáticos e o estado vazio.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Response, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import db
from . import antibot
from . import analytics
from . import roleta
from . import twitch_api
from . import megamu
from . import giveaway_prizes
from .chat_manager import ChatManager
from .giveaway import giveaway
from .state import STATE, log, add_participant, clear_participants, participant_weight

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger('sorteador')

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / 'web'

# Conjunto de WebSockets conectados (painel + overlays)
ws_clients: set[WebSocket] = set()

# Gerenciador unificado de chats (Twitch + Kick)
chat: ChatManager = ChatManager()
from . import env_config


def _sync_connection_env():
    env_config.update({'TWITCH_CLIENT_ID': STATE.bot_twitch_client_id,
        'TWITCH_ACCESS_TOKEN': STATE.bot_twitch_oauth, 'TWITCH_CHANNEL': STATE.twitch_channel,
        'KICK_CHANNEL': STATE.kick_channel,
        'KICK_CHANNEL_ID': STATE.kick_channel_id or '',
        'KICK_CHATROOM_ID': STATE.kick_chatroom_id or '',
        'KICK_RECEIVE_ENABLED': str(STATE.kick_receive_enabled).lower(),
        'KICK_RECEIVE_MODE': STATE.kick_receive_mode,
        'SIMULATION_MODE': str(STATE.simulation_mode).lower(),
        'BOT_TWITCH_ENABLED': str(STATE.bot_twitch_enabled).lower(),
        'BOT_KICK_ENABLED': str(STATE.bot_kick_enabled).lower()})


async def _connected_announcements(platform):
    # Apenas uma escolha explícita de silêncio desativa os anúncios após conectar.
    silent = await db.config_get('chat_silent_' + platform)
    if not silent:
        setattr(STATE, 'bot_' + platform + '_enabled', True)
    _sync_connection_env()

# Disponibiliza o ChatManager global para webhook_server
from .chat_manager import set_chat_manager as _set_cm
_set_cm(chat)


# ==============================================================================
# 📡 BROADCAST
# ==============================================================================
async def broadcast(data: dict[str, Any]) -> None:
    """Envia um evento para todos os WebSockets conectados."""
    if not ws_clients:
        return
    payload = json.dumps(data, default=str, ensure_ascii=False)
    dead: list[WebSocket] = []
    for ws in list(ws_clients):
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_clients.discard(ws)


async def _notify_state() -> None:
    """Notifica todos os clientes WS sobre mudança de estado."""
    await broadcast({'type': 'state', 'state': full_state()})


# ==============================================================================
# 📦 ESTADO COMPLETO (snapshot)
# ==============================================================================
def _build_kick_state() -> dict[str, Any]:
    """Retorna o estado detalhado do Kick para o painel admin."""
    from .kick_chat_auth import get_kick_auth
    from .kick_webhook_server import get_webhook_server
    from . import kick_subscriptions

    result = {
        # OAuth
        'oauth_authenticated': False,
        'oauth_token_valid': False,
        'oauth_username': '',
        'oauth_user_id': '',
        'oauth_user_id': '',
        'client_id': '',
        'redirect_uri': '',
        'channel_slug': '',
        'broadcaster_user_id': '',
        'granted_scopes': [],
        'missing_scopes': [],
        'expires_in_seconds': -1,
        # Ngrok
        'ngrok_connected': False,
        'ngrok_url': '',
        'ngrok_webhook_port': 8766,
        # Subscription
        'subscription_registered': False,
        'subscription_id': '',
        'subscription_name': '',
        'subscription_status': '',
        # Monitor
        'last_webhook_ts': None,
        'last_kick_participant': None,
        'total_messages': 0,
        'last_error': None,
    }

    # OAuth status
    try:
        auth = get_kick_auth()
        auth_status = auth.get_status()
        result['oauth_authenticated'] = auth_status.is_authenticated
        result['oauth_message'] = auth_status.message
        result['oauth_token_valid'] = auth_status.token_valid
        result['oauth_username'] = auth_status.username
        result['oauth_user_id'] = auth_status.user_id
        result['channel_slug'] = auth_status.channel_slug
        result['broadcaster_user_id'] = auth_status.broadcaster_user_id
        result['granted_scopes'] = auth_status.missing_scopes  # will fix below
        result['expires_in_seconds'] = auth_status.expires_in_seconds

        # Get scopes from OAuth object
        oauth = auth._oauth
        if oauth:
            result['send_ready'] = oauth.has_valid_token() and oauth.has_chat_write() and oauth.is_user_token()
            result['oauth_authenticated'] = oauth.get_full_status()['authenticated']
            result['oauth_username'] = oauth._username
            result['client_id'] = oauth.client_id
            result['has_secret'] = bool(oauth.client_secret)
            result['redirect_uri'] = oauth.redirect_uri
            result['granted_scopes'] = list(oauth._granted_scopes) if hasattr(oauth, '_granted_scopes') else []
            required = ['user:read', 'channel:read', 'events:subscribe']
            result['missing_scopes'] = [s for s in required if s not in result['granted_scopes']]
    except Exception as e:
        result['last_error'] = f'OAuth: {e}'

    # Ngrok status
    try:
        server = get_webhook_server()
        from .ngrok_manager import is_ngrok_connected, get_webhook_public_url
        result['ngrok_connected'] = is_ngrok_connected()
        result['ngrok_url'] = get_webhook_public_url() or ''
        result['ngrok_webhook_port'] = server.port
        # Try to get ngrok URL from state
        result.update(getattr(STATE, 'kick_subscription_state', {}))
    except Exception as e:
        result['last_error'] = f'{result["last_error"]}; Ngrok: {e}'

    # Subscription status - skip async check in sync context
    # Note: subscription status will be updated when the subscription endpoints are called
    # This avoids the RuntimeWarning from calling async code in sync context

    # Monitor stats from STATE
    result['last_webhook_ts'] = getattr(STATE, 'last_kick_webhook_ts', None)
    result['last_kick_participant'] = getattr(STATE, 'last_kick_participant', None)
    result['total_messages'] = getattr(STATE, 'kick_total_messages', 0)

    result.update({'receive_mode': STATE.kick_receive_mode, 'receive_channel': STATE.kick_channel,
                   'receive_connected': chat.kick_connected if STATE.kick_receive_mode == 'direct' else bool(STATE.kick_receive_enabled and result['oauth_token_valid'] and result['ngrok_connected'] and result['subscription_registered']),
                   'chatroom_id': chat.kick.chatroom_id or STATE.kick_chatroom_id,
                   'channel_id': chat.kick.channel_id or STATE.kick_channel_id,
                   'receive_transport': chat.kick.transport,
                   'receive_error': chat.kick.last_error})
    return result


def _winner_chat_state():
    if not STATE.is_running:return None
    winner=STATE.current_winner or STATE.winner_claim_pending or (
        STATE.winner_claim_recent if STATE.winner_claim_feedback_until > time.time() else None)
    if winner is None:return None
    awaiting_nick=STATE.current_winner is None and STATE.winner_claim_pending is winner
    participant=STATE.participants.get(winner.platform+':'+winner.username.casefold())
    return {'winner':{'username':winner.username,'platform':winner.platform,'user_id':winner.user_id,
        'avatar_url':winner.avatar_url or (participant.avatar_url if participant else ''),
        'chance_pct':winner.chance_pct, 'award':winner.award},
        'drawn_at':winner.drawn_at,'messages':list(STATE.winner_chat_messages),
        'awaiting_nick':awaiting_nick,'nick_command':STATE.nick_lookup_command,
        'nick_verification':STATE.winner_claim_feedback,
        'captcha_confirmed':bool(winner.captcha_required and winner.captcha_passed)}


def full_state() -> dict[str, Any]:
    """Retorna o estado completo (snapshot) para enviar ao cliente."""
    participant_chances = {
        (entry['platform'], entry['username'].casefold()): entry['chance_pct']
        for entry in giveaway.compute_chances()
    } if STATE.is_running else {}
    return {
        'server': {
            'version': '0.16.2',
            'simulation_mode': STATE.simulation_mode,
        },
        'giveaway': {
            'is_running': STATE.is_running,
            'is_paused': STATE.is_paused,
            'keyword': STATE.keyword,
            'timer': STATE.winner_timer_seconds,
            'count': len(STATE.participants),
            'draw_count': len(STATE.winners),
            'status': STATE.status_message,
            'winner_chat': _winner_chat_state(),
            'current_winner': (
                {
                    'username': STATE.current_winner.username,
                    'platform': STATE.current_winner.platform,
                    'weight': STATE.current_winner.weight,
                    'chance_pct': STATE.current_winner.chance_pct,
                    'award': STATE.current_winner.award,
                    'drawn_at': STATE.current_winner.drawn_at,
                    'captcha_required': STATE.current_winner.captcha_required,
                    'presence_confirmed': STATE.current_winner.presence_confirmed,
                    'captcha_failed': STATE.current_winner.captcha_failed,
                    'avatar_url': STATE.current_winner.avatar_url or next((p.avatar_url for p in STATE.participants.values()
                        if p.platform == STATE.current_winner.platform and p.username.casefold() == STATE.current_winner.username.casefold()), ''),
                }
                if STATE.current_winner else None
            ),
            'winner_deadline': STATE.winner_deadline,
            'draw_reveal_until': STATE.draw_reveal_until,
            'draw_animation_active': STATE.draw_animation_active,
            'auto_advance_timeout': STATE.auto_advance_timeout,
            'captcha_feedback': STATE.captcha_feedback,
            'eligible_count': len(giveaway._build_pool()[0]) if STATE.is_running else 0,
            'prizes': giveaway_prizes.available(),
            'selected_prize': giveaway_prizes.selected(),
            'captcha': antibot.status(),  # omit 'expected' (resposta) do estado público
            'accept_entries_twitch': STATE.accept_entries_twitch,
            'accept_entries_kick': STATE.accept_entries_kick,
            'entry_open_twitch': STATE.entry_open_twitch,
            'entry_open_kick': STATE.entry_open_kick,
            'block_repeat_winner': STATE.block_repeat_winner,
        },
        'viewer_commands': {
            'skip_enabled': STATE.skip_chat_enabled,
            'skip_command': STATE.skip_chat_command,
            'skip_limit': STATE.skip_chat_limit,
            'skip_uses': STATE.skip_chat_uses,
            'nick_enabled': STATE.nick_lookup_enabled,
            'nick_command': STATE.nick_lookup_command,
            'rank_enabled': STATE.rank_lookup_enabled,
            'rank_command': STATE.rank_lookup_command,
        },
        'permissions': {
            'allow_viewers': STATE.allow_viewers,
            'allow_subs': STATE.allow_subs,
            'allow_vips': STATE.allow_vips,
            'allow_mods': STATE.allow_mods, 'platform_mods': STATE.platform_mods,
            'multipliers': STATE.multipliers,
        },
        'antibot': {
            'enabled': STATE.antibot_enabled,
            'types': STATE.antibot_types,
            'timer': STATE.antibot_timer_seconds,
            'selection_mode': 'entry',
            'marked': antibot.marked_participants(),
            'total_decided': len(STATE.participants),
            'random_chance': STATE.antibot_random_chance,
            'max_attempts': STATE.antibot_max_attempts,
            'waive_subs_vips': STATE.captcha_waive_subs_vips,
            'send_to_chat': STATE.captcha_send_to_chat,
        },
        'connections': {
            'twitch': {
                'channel': STATE.twitch_channel,
                'connected': STATE.twitch_connected,
            },
            'kick': {
                'channel': STATE.kick_channel,
                'connected': STATE.kick_connected,
            },
            'simulation_mode': STATE.simulation_mode,
        },
        'bots': {
            'twitch_enabled': STATE.bot_twitch_enabled,
            'twitch_username': STATE.bot_twitch_username,
            'twitch_helix_configured': bool(STATE.bot_twitch_client_id and STATE.bot_twitch_oauth),
            'twitch_client_id': STATE.bot_twitch_client_id,
            'twitch_login': getattr(chat.twitch, 'user_login', '') or STATE.bot_twitch_username,
            'kick_enabled': STATE.bot_kick_enabled,
        },
        # ===== KICK DETAILED STATUS =====
        'kick': _build_kick_state(),
        'roleta': {
            'visible': STATE.roleta_visible,
            'spinning': STATE.roleta_spinning,
            'spin_id': STATE.roleta_current_spin_id,
            'last_ack': STATE.roleta_last_ack,
            'overlay_acknowledged': (STATE.roleta_last_ack > 0
                and (time.time() - STATE.roleta_last_ack) < 30),
            'winner': STATE.roleta_last_winner,
            'nick': STATE.roleta_last_nick,
            'result': STATE.roleta_last_prize,
            'result_index': STATE.roleta_last_index,
            'duration_seconds': STATE.roleta_duration_seconds,
            'extra_spins': STATE.roleta_extra_spins,
            'auto_hide': STATE.roleta_auto_hide,
            'equal_slices': STATE.roleta_equal_slices,
            'result_seconds': STATE.roleta_result_seconds,
            'remaining': STATE.roleta_remaining,
            'total': STATE.roleta_total,
            'current': STATE.roleta_total - STATE.roleta_remaining,
            'active_spin': STATE.roleta_active_spin,  # snapshot do giro em andamento
            'items': [
                {
                    'id': i.id, 'name': i.name, 'weight': i.weight,
                    'active': i.active, 'icon': i.icon,
                }
                for i in STATE.roleta_items
            ],
        },
        'participants': [
            {
                'platform': p.platform,
                'username': p.username,
                'user_id': p.user_id,
                'is_sub': p.is_sub,
                'is_vip': p.is_vip,
                'is_mod': p.is_mod,
                'is_owner': p.is_owner,
                'weight': p.weight,
                'chance_pct': participant_chances.get((p.platform, p.username.casefold()), 0.0),
                'first_seen': p.first_seen,
                'is_winner': p.is_winner,
                'active': p.active,
                'active_changed_at': p.active_changed_at,
                'avatar_url': p.avatar_url,
                'captcha_marked': p.captcha_marked,
                'captcha_status': p.captcha_status,
            }
            for p in STATE.participants.values()
        ],
        'chat_events': STATE.chat_events,
        'chat_event_platforms': STATE.chat_event_platforms,
        'appearance': STATE.appearance,
        'megamu': megamu.status(),
        'chat_messages': list(STATE.chat_messages),
        'message_templates': STATE.message_templates,
        'activity': list(STATE.activity_log)[-50:],
    }


# ==============================================================================
# 🚀 STARTUP / SHUTDOWN
# ==============================================================================
async def _load_state_from_db() -> None:
    """Restaura o estado do banco."""
    cfg = await db.config_get_all()

    if 'twitch_channel' in cfg:
        STATE.twitch_channel = cfg['twitch_channel']
    if 'kick_channel' in cfg:
        STATE.kick_channel = cfg['kick_channel']
    STATE.kick_receive_mode = cfg.get('kick_receive_mode','direct')
    STATE.kick_receive_enabled = bool(cfg.get('kick_receive_enabled',False))
    STATE.kick_chatroom_id = cfg.get('kick_chatroom_id')
    STATE.kick_channel_id = cfg.get('kick_channel_id')
    if 'simulation_mode' in cfg:
        STATE.simulation_mode = bool(cfg['simulation_mode'])
    if 'keyword' in cfg:
        STATE.keyword = cfg['keyword']
    if 'winner_timer_seconds' in cfg:
        STATE.winner_timer_seconds = int(cfg['winner_timer_seconds'])
    entries=cfg.get('entry_preferences',{})
    STATE.accept_entries_twitch=bool(entries.get('twitch',True))
    STATE.accept_entries_kick=bool(entries.get('kick',True))
    STATE.entry_open_twitch=STATE.is_running and STATE.accept_entries_twitch
    STATE.entry_open_kick=STATE.is_running and STATE.accept_entries_kick
    STATE.antibot_timer_seconds = STATE.winner_timer_seconds
    STATE.auto_advance_timeout = bool(cfg.get('auto_advance_timeout',False))
    STATE.custom_giveaway_prizes=cfg.get('custom_giveaway_prizes',[])
    STATE.selected_giveaway_prize=cfg.get('selected_giveaway_prize')
    if 'allow_dual_entry' in cfg:
        STATE.allow_dual_entry = bool(cfg['allow_dual_entry'])
    if 'block_repeat_winner' in cfg:
        STATE.block_repeat_winner = bool(cfg['block_repeat_winner'])
    commands = cfg.get('viewer_commands') or {}
    STATE.skip_chat_enabled = bool(commands.get('skip_enabled', True))
    STATE.skip_chat_command = commands.get('skip_command', '!pular')
    STATE.skip_chat_limit = max(1, min(100, int(commands.get('skip_limit', 3))))
    STATE.nick_lookup_enabled = bool(commands.get('nick_enabled', True))
    STATE.nick_lookup_command = commands.get('nick_command', '!nick')
    STATE.rank_lookup_enabled = bool(commands.get('rank_enabled', True))
    STATE.rank_lookup_command = commands.get('rank_command', '!rank')
    if 'roleta_duration_seconds' in cfg:
        STATE.roleta_duration_seconds = float(cfg['roleta_duration_seconds'])
    if 'roleta_extra_spins' in cfg:
        STATE.roleta_extra_spins = int(cfg['roleta_extra_spins'])

    STATE.roleta_auto_hide = cfg.get('roleta_auto_hide', True)
    STATE.roleta_equal_slices = bool(cfg.get('roleta_equal_slices', False))
    STATE.roleta_result_seconds = float(cfg.get('roleta_result_seconds', 8))
    STATE.chat_events.update(cfg.get('chat_events', {}))
    STATE.chat_event_platforms = cfg.get('chat_event_platforms',{})
    if not cfg.get('message_options_v11'):
        STATE.chat_events.update(entry_accepted=True, entry_repeat=True)
        await db.config_set('chat_events',STATE.chat_events)
        await db.config_set('message_options_v11',True)
    p = cfg.get('permissions', {})
    STATE.allow_viewers = p.get('allow_viewers', True)
    STATE.allow_subs = p.get('allow_subs', True)
    STATE.allow_vips = p.get('allow_vips', True)
    STATE.allow_mods = p.get('allow_mods', False)
    STATE.platform_mods = p.get('platform_mods', {})
    if 'multipliers' in p:
        STATE.multipliers = p['multipliers']
    if 'bot_twitch_oauth' in cfg:
        STATE.bot_twitch_oauth = cfg['bot_twitch_oauth']
    if 'bot_twitch_client_id' in cfg:
        STATE.bot_twitch_client_id = cfg['bot_twitch_client_id']

    a = cfg.get('antibot', {})
    STATE.antibot_enabled = bool(a.get('enabled', False))
    STATE.antibot_types = a.get('types', STATE.antibot_types)
    STATE.antibot_timer_seconds = STATE.winner_timer_seconds
    STATE.antibot_random_chance = int(a.get('random_chance', 50))
    STATE.antibot_max_attempts = max(0,min(100,int(a.get('max_attempts',3))))
    STATE.captcha_waive_subs_vips = bool(a.get('waive_subs_vips', True))
    STATE.captcha_send_to_chat = bool(a.get('send_to_chat', False))
    STATE.chat_events['captcha_challenge'] = STATE.captcha_send_to_chat

    if 'message_templates' in cfg:
        for event, templates in cfg['message_templates'].items():
            if isinstance(templates, dict) and event in STATE.message_templates:
                STATE.message_templates[event].update({platform: template for platform, template in templates.items()
                    if platform in ('twitch', 'kick') and isinstance(template, str)})
    # Em versões anteriores o painel podia salvar campos vazios. Recoloca
    # somente esses campos nos padrões, mantendo qualquer texto personalizado.
    from .state import _default_messages
    for event, defaults in _default_messages().items():
        for platform, default in defaults.items():
            if not STATE.message_templates.get(event, {}).get(platform, '').strip():
                STATE.message_templates.setdefault(event, {})[platform] = default
    # Atualiza apenas textos padrão antigos; preserva mensagens personalizadas.
    for platform in ('twitch','kick'):
        legacy = {'entry_accepted':'✅ {nome}, sua inscrição foi confirmada!',
                  'entry_repeat':'⚠️ {nome}, você já está participando!',
                  'winner_no_response':'⏰ {nome} não respondeu a tempo. Sorteando novo vencedor...'}
        from .state import _default_messages
        for event, old_text in legacy.items():
            if STATE.message_templates[event].get(platform) == old_text:
                STATE.message_templates[event][platform] = _default_messages()[event][platform]
        for event,old_text in {
            'entry_accepted':'✅ {nome}, inscrição confirmada! Chance atual: {chance}% ({participantes} participantes).',
            'entry_repeat':'ℹ️ {nome}, você já está participando! Chance atual: {chance}%.',
            # Texto padrão da v20; a nova etapa não repete "presença confirmada"
            # depois de o CAPTCHA já ter sido validado.
            'winner_claim_instructions':'🎁 @{nome}, presença confirmada! Para receber {premio}, envie {comando_nick} NomeDoPersonagem no chat.',
        }.items():
            if STATE.message_templates[event].get(platform)==old_text:
                STATE.message_templates[event][platform]=_default_messages()[event][platform]
        # Atualiza somente o antigo texto padrão da v24; não altera textos
        # personalizados na aba Mensagens.
        old_claim='🎁 @{nome}, mande {comando_nick} NomeDoPersonagem para receber seu prêmio ({premio}).'
        if STATE.message_templates['winner_claim_instructions'].get(platform)==old_claim:
            STATE.message_templates['winner_claim_instructions'][platform]=_default_messages()['winner_claim_instructions'][platform]
    if 'appearance' in cfg:
        STATE.appearance.update(cfg['appearance'])
        if STATE.appearance.get('primary_color', '').lower() in {'#ffd400', '#ffcc00'}:
            STATE.appearance['primary_color'] = '#79e8a4'
            await db.config_set('appearance', STATE.appearance)
    if 'bots' in cfg:
        b = cfg['bots']
        STATE.bot_twitch_enabled = bool(b.get('twitch_enabled', False))
        STATE.bot_twitch_username = b.get('twitch_username', '')
        STATE.bot_kick_enabled = bool(b.get('kick_enabled', False))

    saved_env = env_config.read()
    if saved_env.get('SIMULATION_MODE'):
        STATE.simulation_mode = saved_env['SIMULATION_MODE'].lower() == 'true'
    if saved_env.get('KICK_RECEIVE_ENABLED'):
        STATE.kick_receive_enabled = saved_env['KICK_RECEIVE_ENABLED'].lower() == 'true'
    if saved_env.get('KICK_RECEIVE_MODE') in ('direct', 'webhook'):
        STATE.kick_receive_mode = saved_env['KICK_RECEIVE_MODE']
    for key, attribute in [('KICK_CHANNEL_ID', 'kick_channel_id'), ('KICK_CHATROOM_ID', 'kick_chatroom_id')]:
        if saved_env.get(key, '').isdigit() and int(saved_env[key]) > 0:
            setattr(STATE, attribute, int(saved_env[key]))
    for key, attribute in [('TWITCH_CLIENT_ID', 'bot_twitch_client_id'),
                           ('TWITCH_ACCESS_TOKEN', 'bot_twitch_oauth'),
                           ('TWITCH_CHANNEL', 'twitch_channel'), ('KICK_CHANNEL', 'kick_channel')]:
        if saved_env.get(key): setattr(STATE, attribute, saved_env[key])
    for platform in ('twitch', 'kick'):
        value = saved_env.get('BOT_' + platform.upper() + '_ENABLED')
        enabled = value.lower() == 'true' if value else not cfg.get('chat_silent_' + platform, False)
        setattr(STATE, 'bot_' + platform + '_enabled', enabled)
        if value:
            await db.config_set('chat_silent_' + platform, not enabled)
    _sync_connection_env()

    # Carrega roleta
    items = await db.roleta_list()
    from .state import RoletaItem
    STATE.roleta_items = [
        RoletaItem(
            id=i['id'], name=i['name'], weight=float(i['weight']),
            active=i['active'], icon=i.get('icon', '🎁'),
        )
        for i in items
    ]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup e shutdown do servidor."""
    log('🟢 Iniciando Sorteador Geral...')
    await db.init()
    await _load_state_from_db()
    log('✅ Estado carregado do banco')

    # Liga o callback de mudança de participantes pra notificar os overlays
    chat._on_change = _notify_state
    async def notify_chat_message(message):
        await broadcast({'type': 'chat_message', 'message': message})
    chat.on_chat_message = notify_chat_message
    # Liga o callback do motor de sorteio pra notificar quando houver mudanças
    giveaway.on_change = _notify_state
    giveaway.chat = chat
    roleta.on_change = _notify_state
    from .kick_webhook_server import set_app_loop
    set_app_loop(asyncio.get_running_loop())

    # Carrega itens da roleta do DB pro state
    await roleta.load_items_from_db()

    # Inicia task de atualização de status de conexão
    status_task = asyncio.create_task(_status_updater())

    # Se tem canal configurado e não é modo simulação, conecta automaticamente
    if STATE.twitch_channel and not STATE.simulation_mode:
        from .twitch_chat import TokenInvalidError, ScopeMissingError
        try:
            await chat.connect_twitch(
                STATE.twitch_channel,
                STATE.bot_twitch_client_id,
                STATE.bot_twitch_oauth,
            )
        except TokenInvalidError:
            log('⚠️ Token Twitch inválido/expirado. Configure novas credenciais.', 'warn')
        except ScopeMissingError as e:
            log(f'⚠️ Token sem scope necessário: {e.missing_scopes}', 'warn')
        except ValueError as e:
            log(f'⚠️ Credenciais Twitch ausentes: {e}', 'warn')
        except Exception as e:
            log(f'⚠️ Falha ao reconectar Twitch: {e}', 'warn')

    # Kick desabilitado — API pública mudou, exige auth. Não tenta reconectar.

    # Inicializa kick_chat_auth com referência ao oauth
    try:
        from .kick_oauth import get_oauth, setup_oauth
        from .kick_chat_auth import setup_kick_auth
        try:
            oauth = get_oauth()
        except RuntimeError:
            # OAuth não configurado ainda - cria um placeholder
            saved = (await db.config_get_all()).get('kick_oauth_config', {})
            local = env_config.read()
            oauth = setup_oauth(client_id=local.get('KICK_CLIENT_ID') or saved.get('client_id', ''),
                redirect_uri=local.get('KICK_REDIRECT_URI') or saved.get('redirect_uri', 'http://localhost:8777/api/oauth/kick/callback'),
                client_secret=local.get('KICK_CLIENT_SECRET', ''))
        if oauth._access_token:
            oauth._save_tokens()
        setup_kick_auth(oauth)
        logger.info('KickAuthConnection inicializado')
    except Exception as e:
        logger.warning(f'Falha ao inicializar KickAuthConnection: {e!r}')

    # Inicia webhook server para Kick (porta separada, 8766)
    try:
        from .kick_webhook_server import start_webhook_server, stop_webhook_server
        from .ngrok_manager import start_ngrok, stop_ngrok, get_webhook_public_url, is_ngrok_connected
        if start_webhook_server():
            logger.info('Webhook server iniciado em 127.0.0.1:8766')
        else:
            logger.warning('Falha ao iniciar webhook server')
    except Exception as e:
        logger.warning(f'Falha ao iniciar webhook server: {e!r}')

    async def reconnect_kick_reader():
        if STATE.kick_receive_enabled and STATE.kick_channel and STATE.kick_receive_mode == 'direct' and not STATE.simulation_mode:
            await chat.connect_kick(channel=STATE.kick_channel,simulate=False,mode='direct',
                                    chatroom_id=STATE.kick_chatroom_id,channel_id=STATE.kick_channel_id)
            await _notify_state()
    kick_startup = asyncio.create_task(reconnect_kick_reader())
    async def refresh_kick_session():
        while True:
            try:
                from .kick_oauth import get_oauth
                saved_oauth = get_oauth()
                if saved_oauth._refresh_token and not saved_oauth.has_valid_token():
                    success, _ = await saved_oauth.ensure_valid_token()
                    if success: await _notify_state()
            except Exception:
                logger.warning('Não foi possível renovar a sessão Kick. Nova tentativa em 30 segundos.')
            await asyncio.sleep(30)
    kick_refresh = asyncio.create_task(refresh_kick_session())
    async def refresh_awards():
        while True:
            info=megamu.status()
            if info['enabled'] and info['dv'] and info['has_key']:
                try: await megamu.refresh()
                except ValueError: pass
                await _notify_state()
            await asyncio.sleep(5)
    awards_task = asyncio.create_task(refresh_awards())
    yield

    awards_task.cancel()
    try: await awards_task
    except asyncio.CancelledError: pass
    kick_refresh.cancel()
    try: await kick_refresh
    except asyncio.CancelledError: pass
    kick_startup.cancel()
    try:await kick_startup
    except asyncio.CancelledError:pass
    log('🔴 Encerrando servidor')
    status_task.cancel()
    await roleta.set_visible(False)
    await chat.shutdown()
    # Encerra ngrok e webhook server
    try:
        from .ngrok_manager import stop_ngrok
        from .kick_webhook_server import stop_webhook_server
        stop_ngrok()
        stop_webhook_server()
    except Exception:
        pass
    # Salva config principal
    await db.config_set('twitch_channel', STATE.twitch_channel)
    await db.config_set('kick_channel', STATE.kick_channel)
    await db.config_set('kick_receive_mode', STATE.kick_receive_mode)
    await db.config_set('kick_receive_enabled', STATE.kick_receive_enabled)
    await db.config_set('kick_chatroom_id', STATE.kick_chatroom_id)
    await db.config_set('kick_channel_id', STATE.kick_channel_id)
    await db.config_set('simulation_mode', STATE.simulation_mode)
    await db.config_set('keyword', STATE.keyword)
    await db.config_set('winner_timer_seconds', STATE.winner_timer_seconds)
    await db.config_set('entry_preferences',{'twitch':STATE.accept_entries_twitch,'kick':STATE.accept_entries_kick})
    await db.config_set('allow_dual_entry', STATE.allow_dual_entry)
    await db.config_set('block_repeat_winner', STATE.block_repeat_winner)
    await db.config_set('permissions', {
        'allow_viewers': STATE.allow_viewers,
        'allow_subs': STATE.allow_subs,
        'allow_vips': STATE.allow_vips,
        'allow_mods': STATE.allow_mods, 'platform_mods': STATE.platform_mods,
        'multipliers': STATE.multipliers,
    })
    await db.config_set('bot_twitch_oauth', STATE.bot_twitch_oauth)
    await db.config_set('bot_twitch_client_id', STATE.bot_twitch_client_id)
    await db.config_set('antibot', {
        'enabled': STATE.antibot_enabled,
        'types': STATE.antibot_types,
        'timer': STATE.antibot_timer_seconds,
        'selection_mode': 'entry',
        'random_chance': STATE.antibot_random_chance,
        'max_attempts': STATE.antibot_max_attempts,
        'waive_subs_vips': STATE.captcha_waive_subs_vips,
        'send_to_chat': STATE.captcha_send_to_chat,
    })
    await db.config_set('message_templates', STATE.message_templates)
    await db.config_set('appearance', STATE.appearance)
    await db.config_set('bots', {
        'twitch_enabled': STATE.bot_twitch_enabled,
        'twitch_username': STATE.bot_twitch_username,
        'kick_enabled': STATE.bot_kick_enabled,
    })


async def _status_updater() -> None:
    """Loop que sincroniza STATE.twitch_connected/kick_connected e notifica clientes.

    Roda a cada 2s. Custo: zero quando nada muda.
    """
    try:
        while True:
            await asyncio.sleep(2)
            changed = False
            new_t = chat.twitch_connected
            k = _build_kick_state()
            new_k = k['receive_connected']
            if new_t != STATE.twitch_connected:
                STATE.twitch_connected = new_t
                changed = True
            if new_k != STATE.kick_connected:
                STATE.kick_connected = new_k
                changed = True
            if changed:
                await _notify_state()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.debug(f'status_updater erro: {e}')


app = FastAPI(title='Sorteador Geral', lifespan=lifespan)

# Servir arquivos estáticos (CSS, JS, imagens) a partir de web/
# /admin/static/* -> web/admin/*  (css, js, img)
# /overlay-static/* -> web/overlay/* (caso queira assets compartilhados)
app.mount('/admin/static', StaticFiles(directory=str(WEB_DIR / 'admin')), name='admin-static')
app.mount('/overlay-static', StaticFiles(directory=str(WEB_DIR / 'overlay')), name='overlay-static')
app.mount('/static', StaticFiles(directory=str(WEB_DIR / 'static')), name='static')


# ==============================================================================
# 📁 ARQUIVOS
# ==============================================================================
@app.get('/')
async def index():
    return RedirectResponse('/admin/')


@app.get('/admin/')
@app.get('/admin/index.html')
async def admin_index():
    return FileResponse(WEB_DIR / 'admin' / 'index.html', headers={'Cache-Control':'no-store'})


@app.get('/overlay/sorteio')
@app.get('/overlay/sorteio/')
@app.get('/overlay/sorteio/index.html')
async def overlay_sorteio():
    return FileResponse(WEB_DIR / 'overlay' / 'sorteio' / 'index.html', headers={'Cache-Control': 'no-store'})


@app.get('/overlay/roleta')
@app.get('/overlay/roleta/')
@app.get('/overlay/roleta/index.html')
async def overlay_roleta():
    return FileResponse(WEB_DIR / 'overlay' / 'roleta' / 'index.html')


@app.get('/overlay/captcha')
@app.get('/overlay/captcha/')
@app.get('/overlay/captcha/index.html')
async def overlay_captcha():
    return FileResponse(WEB_DIR / 'overlay' / 'captcha' / 'index.html')


@app.get('/chats-setup.html')
async def chats_setup():
    return FileResponse(WEB_DIR / 'chats-setup.html')


# ==============================================================================
# 🔌 WEBSOCKET
# ==============================================================================
@app.websocket('/ws')
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    try:
        await ws.send_text(json.dumps({
            'type': 'init',
            'state': full_state(),
        }, default=str, ensure_ascii=False))
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if msg.get('action') == 'ping':
                await ws.send_text(json.dumps({'type': 'pong'}))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f'WS erro: {e}')
    finally:
        ws_clients.discard(ws)


# ==============================================================================
# 📡 API
# ==============================================================================
@app.get('/api/chat/twitch/channels')
async def api_twitch_chat_channels():
    from .twitch_channels import describe
    return await describe()


@app.get('/api/state')
async def api_state():
    return JSONResponse(full_state())


@app.get('/api/health')
async def api_health():
    return {'ok': True, 'version': '0.8.0'}


@app.get('/api/config/env/status')
async def api_env_status(request: Request):
    """Resumo visual da configuração local, sem devolver nenhum segredo."""
    _require_localhost(request)
    saved = env_config.read()
    public_keys = (
        'TWITCH_CLIENT_ID', 'TWITCH_CHANNEL', 'KICK_CHANNEL',
        'KICK_CHANNEL_ID', 'KICK_CHATROOM_ID', 'KICK_RECEIVE_ENABLED',
        'KICK_RECEIVE_MODE', 'SIMULATION_MODE', 'BOT_TWITCH_ENABLED',
        'BOT_KICK_ENABLED', 'KICK_CLIENT_ID', 'KICK_REDIRECT_URI',
        'MEGAMU_DV', 'MEGAMU_ENABLED',
    )
    secret_keys = (
        'TWITCH_ACCESS_TOKEN', 'KICK_CLIENT_SECRET', 'KICK_ACCESS_TOKEN',
        'KICK_REFRESH_TOKEN', 'KICK_TOKEN_METADATA', 'MEGAMU_KEY',
    )
    return {
        'ok': True,
        'file_exists': env_config.ENV_PATH.is_file(),
        'fields': {key: saved.get(key, '') for key in public_keys},
        'secrets_configured': {
            key: bool(saved.get(key) and saved[key] != '{}') for key in secret_keys
        },
    }


class LocalModeRequest(BaseModel):
    simulation_mode: bool


@app.post('/api/config/env/mode')
async def api_env_mode(req: LocalModeRequest, request: Request):
    """Alterna o modo real/simulado sem alterar tokens nem canais."""
    _require_localhost(request)
    if req.simulation_mode and (chat.twitch.connected or chat.kick_connected):
        raise HTTPException(409, 'Desconecte os chats antes de ativar o modo simulação.')
    STATE.simulation_mode = req.simulation_mode
    await db.config_set('simulation_mode', req.simulation_mode)
    _sync_connection_env()
    await _notify_state()
    return {'ok': True, 'simulation_mode': STATE.simulation_mode}


# ==============================================================================
# 🔌 API DE CHATS (Twitch + Kick)
# ==============================================================================
class ConnectRequest(BaseModel):
    channel: str = ''
    bot_username: str = ''
    bot_oauth: str = ''
    simulation: bool = False  # Modo simulação para Kick


@app.post('/api/chat/twitch/connect')
async def api_twitch_connect(req: ConnectRequest):
    """Conecta ao chat Twitch via EventSub WebSocket.
    Requer Client-ID + OAuth token configurados em Helix.
    Sem credencial, retorna 400 explicando o que falta."""
    from .twitch_chat import (
        TwitchAuthError, TokenInvalidError, TokenExpiredError, ScopeMissingError
    )
    try:
        if not STATE.bot_twitch_client_id or not STATE.bot_twitch_oauth:
            raise HTTPException(
                400,
                'Twitch EventSub exige Client-ID + OAuth token. '
                'Configure a conta em Conexões antes de conectar.'
            )
        await chat.connect_twitch(req.channel)
        STATE.simulation_mode = False
        await db.config_set('simulation_mode', False)
        STATE.twitch_channel = req.channel.strip().lstrip('#@').lower()
        await db.config_set('twitch_channel', STATE.twitch_channel)
        await _connected_announcements('twitch')
        await _notify_state()
        return {
            'ok': True,
            'channel': STATE.twitch_channel,
            'eventsub': True,
        }
    except twitch_api.TokenValidationUnavailable as e:
        raise HTTPException(503,str(e))
    except TokenInvalidError as e:
        raise HTTPException(401, str(e))
    except TokenExpiredError as e:
        raise HTTPException(401, str(e))
    except ScopeMissingError as e:
        raise HTTPException(403, str(e))
    except TwitchAuthError as e:
        raise HTTPException(401, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception('Falha Twitch connect')
        raise HTTPException(500, f'Falha: {e!r}')


@app.post('/api/chat/twitch/disconnect')
async def api_twitch_disconnect():
    await chat.disconnect_twitch()
    await _notify_state()
    return {'ok': True}


class KickConnectRequest(BaseModel):
    channel: str = ''
    simulation: bool = False
    mode: Literal['direct','webhook'] = 'direct'
    chatroom_id: int | None = Field(default=None,ge=1)
    channel_id: int | None = Field(default=None,ge=1)


class KickReceiveSaveRequest(BaseModel):
    channel: str = Field(default='', max_length=100)
    mode: Literal['direct', 'webhook'] = 'direct'
    chatroom_id: int | None = Field(default=None, ge=1)
    channel_id: int | None = Field(default=None, ge=1)
    reconnect_at_start: bool = False


@app.post('/api/chat/kick/save')
async def api_kick_receive_save(req: KickReceiveSaveRequest, request: Request):
    """Permite salvar o canal da Kick no .env sem conectar ao chat."""
    _require_localhost(request)
    channel = req.channel.strip().removeprefix('@').lower()
    if req.reconnect_at_start and not channel:
        raise HTTPException(400, 'Informe o canal antes de ativar a reconexão automática.')
    changed = (channel != STATE.kick_channel or req.mode != STATE.kick_receive_mode
               or req.chatroom_id != STATE.kick_chatroom_id
               or req.channel_id != STATE.kick_channel_id)
    if changed and chat.kick_connected:
        raise HTTPException(409, 'Desconecte o chat da Kick antes de alterar o canal ou seus IDs.')
    STATE.kick_channel = channel
    STATE.kick_receive_mode = req.mode
    STATE.kick_chatroom_id = req.chatroom_id
    STATE.kick_channel_id = req.channel_id
    STATE.kick_receive_enabled = req.reconnect_at_start
    for key, value in (
        ('kick_channel', channel), ('kick_receive_mode', req.mode),
        ('kick_chatroom_id', req.chatroom_id), ('kick_channel_id', req.channel_id),
        ('kick_receive_enabled', req.reconnect_at_start),
    ):
        await db.config_set(key, value)
    _sync_connection_env()
    await _notify_state()
    return {'ok': True, 'channel': channel, 'reconnect_at_start': req.reconnect_at_start}


@app.post('/api/chat/kick/connect')
async def api_kick_connect(req: KickConnectRequest):
    """Recepção direta não depende de OAuth nem de túnel; simulação é explícita."""
    channel = req.channel.strip().lstrip('@').lower()
    if not channel:
        from .kick_oauth import get_oauth
        try:
            info = get_oauth().get_channel_info()
            channel = info.slug if info else ''
        except RuntimeError:pass
    if not channel:
        raise HTTPException(400,'Informe o canal da Kick para receber mensagens.')
    success,message = await chat.connect_kick(channel=channel,simulate=req.simulation,
        oauth_status_check=True,mode=req.mode,chatroom_id=req.chatroom_id,channel_id=req.channel_id)
    if not success:
        await _notify_state()
        raise HTTPException(400,message)
    STATE.kick_channel = channel
    STATE.kick_receive_mode = req.mode
    STATE.kick_receive_enabled = True
    STATE.kick_chatroom_id = chat.kick.chatroom_id or req.chatroom_id
    STATE.kick_channel_id = chat.kick.channel_id or req.channel_id
    STATE.kick_connected = chat.kick_connected
    STATE.simulation_mode = req.simulation
    await _connected_announcements('kick')
    for key,value in [('kick_channel',channel),('kick_receive_mode',req.mode),
                      ('kick_chatroom_id',STATE.kick_chatroom_id),('kick_channel_id',STATE.kick_channel_id),('kick_receive_enabled',True),('simulation_mode',req.simulation)]:
        await db.config_set(key,value)
    await _notify_state()
    return {'ok':True,'channel':channel,'mode':req.mode,'simulation':req.simulation}


@app.post('/api/chat/kick/disconnect')
async def api_kick_disconnect():
    await chat.disconnect_kick()
    STATE.kick_connected = False
    STATE.kick_receive_enabled = False
    _sync_connection_env()
    await db.config_set('kick_receive_enabled',False)
    chat.kick.last_error = ''
    await _notify_state()
    return {'ok': True}


# ==============================================================================
# 🔐 API OAUTH KICK
# ==============================================================================

def _require_localhost(request):
    """Verifica se a requisição vem de localhost.

    Proteger rotas administrativas de acesso remoto.
    """
    from fastapi import Request
    client_host = request.client.host if request.client else ''
    # 127.0.0.1 ou localhost
    if client_host not in ('127.0.0.1', 'localhost', '::1', '::ffff:127.0.0.1'):
        raise HTTPException(403, 'Acesso negado. Rotas administrativas requerem localhost.')


class KickOAuthConfig(BaseModel):
    client_id: str
    redirect_uri: str
    client_secret: str = ''


class KickOAuthStartRequest(BaseModel):
    include_chat: bool = False


@app.post('/api/oauth/kick/config')
async def api_kick_oauth_config(req: KickOAuthConfig, request: Request):
    """Define configuração OAuth do Kick (client_id, redirect_uri, client_secret).

    O client_secret é armazenado em memória apenas e nunca persiste no banco.
    Requer acesso localhost.
    """
    _require_localhost(request)

    from .kick_oauth import setup_oauth, get_oauth

    try: previous = get_oauth()
    except RuntimeError: previous = None
    secret = req.client_secret.strip() or (previous.client_secret if previous and previous.client_id == req.client_id.strip() else '')
    oauth = setup_oauth(
        client_id=req.client_id.strip(),
        redirect_uri=req.redirect_uri.strip(),
        client_secret=secret,
    )
    from .kick_chat_auth import setup_kick_auth
    setup_kick_auth(oauth)
    await db.config_set('kick_oauth_config', {'client_id': oauth.client_id, 'redirect_uri': oauth.redirect_uri})
    env_config.update({'KICK_CLIENT_ID': oauth.client_id, 'KICK_REDIRECT_URI': oauth.redirect_uri,
                       'KICK_CLIENT_SECRET': oauth.client_secret})
    return {
        'ok': True,
        'config': oauth.get_config_dict(),
    }


@app.get('/api/oauth/kick/status')
async def api_kick_oauth_status():
    """Retorna status completo da autenticação OAuth.

    Diferencia status de autenticação OAuth do status de conexão ao chat.
    Nunca expõe credenciais confidenciais.
    """
    from .kick_oauth import get_oauth

    try:
        oauth = get_oauth()
        return oauth.get_full_status()
    except RuntimeError:
        return {
            'authenticated': False,
            'token_valid': False,
            'is_user_token': False,
            'has_required_scopes': False,
            'username': '',
            'user_id': '',
            'channel_slug': '',
            'broadcaster_user_id': '',
            'granted_scopes': [],
            'missing_scopes': [],
            'expires_at': 0,
            'expires_in_seconds': -1,
        }


@app.post('/api/oauth/kick/start')
async def api_kick_oauth_start(req: KickOAuthStartRequest):
    """Inicia fluxo OAuth e retorna URL de autorização.

    O cliente deve abrir a URL no navegador e aguardar callback.
    """
    from .kick_oauth import get_oauth

    try:
        oauth = get_oauth()
    except RuntimeError:
        raise HTTPException(400, 'OAuth não configurado. Envie /api/oauth/kick/config primeiro.')

    try:
        url = oauth.start_authorization(include_chat=req.include_chat)
        return {
            'ok': True,
            'authorization_url': url,
        }
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get('/api/oauth/kick/callback')
async def api_kick_oauth_callback(code: str = '', state: str = ''):
    """Callback OAuth - recebe authorization_code e troca por tokens.

    Para uso manual (sem browser), use /api/oauth/kick/exchange diretamente.
    """
    from .kick_oauth import get_oauth

    if not code:
        raise HTTPException(400, 'code é obrigatório')
    if not state:
        raise HTTPException(400, 'state é obrigatório')

    try:
        oauth = get_oauth()
    except RuntimeError:
        raise HTTPException(400, 'OAuth não configurado. Envie /api/oauth/kick/config primeiro.')

    # Valida state
    valid, code_verifier = oauth.validate_callback(code, state)
    if not valid:
        raise HTTPException(400, f'Callback inválido: {code_verifier}')

    # Troca code por tokens
    success, error = await oauth.exchange_code_for_tokens(code, code_verifier)
    if not success:
        raise HTTPException(400, f'Falha ao trocar tokens: {error}')

    STATE.simulation_mode = False
    channel = oauth.get_channel_info()
    if not STATE.kick_channel:
        STATE.kick_channel = channel.slug if channel else ''
    await db.config_set('simulation_mode', False)
    await db.config_set('kick_channel', STATE.kick_channel)
    await _connected_announcements('kick')
    await _notify_state()
    return {
        'ok': True,
        'authorized': True,
        'username': oauth._username,
        'user_id': oauth._user_id,
    }


class KickOAuthExchangeRequest(BaseModel):
    code: str
    state: str


@app.post('/api/oauth/kick/exchange')
async def api_kick_oauth_exchange(req: KickOAuthExchangeRequest, request: Request):
    """Troca authorization_code por tokens manualmente.

    Útil quando o callback é tratado externamente.
    Requer acesso localhost.
    """
    _require_localhost(request)
    from .kick_oauth import get_oauth

    if not req.code:
        raise HTTPException(400, 'code é obrigatório')
    if not req.state:
        raise HTTPException(400, 'state é obrigatório')

    try:
        oauth = get_oauth()
    except RuntimeError:
        raise HTTPException(400, 'OAuth não configurado. Envie /api/oauth/kick/config primeiro.')

    # Valida state
    valid, code_verifier = oauth.validate_callback(req.code, req.state)
    if not valid:
        raise HTTPException(400, f'Callback inválido: {code_verifier}')

    # Troca code por tokens
    success, error = await oauth.exchange_code_for_tokens(req.code, code_verifier)
    if not success:
        raise HTTPException(400, f'Falha ao trocar tokens: {error}')

    STATE.simulation_mode = False
    channel = oauth.get_channel_info()
    if not STATE.kick_channel:
        STATE.kick_channel = channel.slug if channel else ''
    await db.config_set('simulation_mode', False)
    await db.config_set('kick_channel', STATE.kick_channel)
    await _notify_state()
    return {
        'ok': True,
        'authorized': True,
        'username': oauth._username,
        'user_id': oauth._user_id,
    }


class KickOAuthRefreshRequest(BaseModel):
    pass


@app.post('/api/oauth/kick/refresh')
async def api_kick_oauth_refresh(req: KickOAuthRefreshRequest, request: Request):
    """Renova tokens usando refresh_token.
    Requer acesso localhost.
    """
    _require_localhost(request)
    from .kick_oauth import get_oauth

    try:
        oauth = get_oauth()
    except RuntimeError:
        raise HTTPException(400, 'OAuth não configurado.')

    if not oauth.has_valid_token() and not oauth._refresh_token:
        raise HTTPException(400, 'Não há token para renovar. Faça login primeiro.')

    success, error = await oauth.refresh_tokens()
    if not success:
        raise HTTPException(400, f'Falha ao renovar tokens: {error}')

    return {
        'ok': True,
        'username': oauth._username,
    }


@app.post('/api/oauth/kick/logout')
async def api_kick_oauth_logout(request: Request):
    """Encerra sessão OAuth (limpa tokens).
    Requer acesso localhost.
    """
    _require_localhost(request)
    from .kick_oauth import get_oauth

    try:
        oauth = get_oauth()
        oauth.clear_tokens()
    except RuntimeError:
        pass  # Ignora se não configurado

    return {'ok': True}


# =============================================================================
# WEBHOOKS KICK
# =============================================================================

@app.post('/api/webhooks/kick')
async def api_kick_webhook(request: Request):
    """Receptor de webhooks oficiais da Kick.

    Valida assinatura RSA-SHA256, verifica timestamp e deduplica eventos.
    Não modifica estado do sorteio nesta etapa.

    Headers esperados:
    - Kick-Event-Message-Id: ID único do evento
    - Kick-Event-Message-Timestamp: RFC3339 timestamp
    - Kick-Event-Signature: Assinatura Base64
    - Kick-Event-Type: Tipo do evento (ex: chat.message.sent)
    - Kick-Event-Version: Versão do evento
    - Kick-Event-Subscription-Id: ID da assinatura

    Documentação:
    https://github.com/KickEngineering/KickDevDocs/blob/main/events/webhook-security.md
    """
    from .kick_webhook import get_validator, verify_broadcaster
    from .kick_chat_auth import get_kick_auth

    # Lê corpo cru ANTES de qualquer validação
    try:
        raw_body = await request.body()
    except Exception as e:
        logger.warning(f'Webhook: falha ao ler corpo: {e!r}')
        raise HTTPException(400, 'Falha ao ler corpo da requisição')

    # Extrai headers
    headers = {
        'Kick-Event-Message-Id': request.headers.get('Kick-Event-Message-Id', ''),
        'Kick-Event-Message-Timestamp': request.headers.get('Kick-Event-Message-Timestamp', ''),
        'Kick-Event-Signature': request.headers.get('Kick-Event-Signature', ''),
        'Kick-Event-Type': request.headers.get('Kick-Event-Type', ''),
        'Kick-Event-Version': request.headers.get('Kick-Event-Version', ''),
        'Kick-Event-Subscription-Id': request.headers.get('Kick-Event-Subscription-Id', ''),
    }

    # Valida evento
    validator = get_validator()
    is_valid, error, event = await validator.validate_event(headers, raw_body)

    if not is_valid:
        # Log apenas o tipo de erro, nunca dados sensíveis
        logger.warning(f'Webhook rejeitado: {error}')
        raise HTTPException(400, error)

    # Verifica broadcaster contra OAuth configurado
    auth = get_kick_auth()
    status = auth.get_status()

    if status.broadcaster_user_id and not verify_broadcaster(event, status.broadcaster_user_id):
        logger.warning(f'Webhook: broadcaster mismatch (event={event.broadcaster_user_id}, config={status.broadcaster_user_id})')
        raise HTTPException(400, 'Broadcaster não corresponde ao canal configurado')

    # Loga evento válido (sem dados sensíveis)
    logger.info(f'Webhook válido: type={event.event_type}, msg_id={event.message_id[:16]}...')

    if event.event_type == 'chat.message.sent':
        STATE.last_kick_webhook_ts = time.time()
        STATE.kick_total_messages = getattr(STATE, 'kick_total_messages', 0) + 1
        STATE.last_kick_participant = event.sender_username
        chat.handle_kick_webhook_event(event)
    # Responde rapidamente
    return {
        'ok': True,
        'event_type': event.event_type,
        'event_version': event.event_version,
    }


# =============================================================================
# NGROK TUNNEL MANAGEMENT
# =============================================================================

class NgrokConnectRequest(BaseModel):
    pass


@app.post('/api/ngrok/connect')
async def api_ngrok_connect(request: Request):
    """Inicia o túnel ngrok para webhooks.

    Requer ngrok instalado e authtoken configurado.
    Requer acesso localhost.
    """
    _require_localhost(request)
    from .ngrok_manager import start_ngrok, get_webhook_public_url, is_ngrok_connected

    if is_ngrok_connected():
        return {
            'ok': True,
            'connected': True,
            'url': get_webhook_public_url(),
            'message': 'Túnel já está ativo',
        }

    success, result = start_ngrok()

    if success:
        return {
            'ok': True,
            'connected': True,
            'url': result,
            'message': 'Túnel ngrok iniciado com sucesso',
        }
    else:
        return {
            'ok': True,
            'connected': False,
            'url': '',
            'message': result,  # Contém instruções de configuração
        }


@app.post('/api/ngrok/disconnect')
async def api_ngrok_disconnect(request: Request):
    """Encerra o túnel ngrok.
    Requer acesso localhost.
    """
    _require_localhost(request)
    from .ngrok_manager import stop_ngrok, is_ngrok_connected

    if not is_ngrok_connected():
        return {'ok': True, 'connected': False}

    stop_ngrok()
    return {'ok': True, 'connected': False}


@app.get('/api/ngrok/status')
async def api_ngrok_status(request: Request):
    """Retorna status do túnel ngrok.
    Requer acesso localhost.
    """
    _require_localhost(request)
    from .ngrok_manager import is_ngrok_connected, get_webhook_public_url

    connected = is_ngrok_connected()

    return {
        'connected': connected,
        'url': get_webhook_public_url() if connected else '',
        'webhook_local_url': 'http://127.0.0.1:8766/api/webhooks/kick',
    }


# =============================================================================
# KICK EVENT SUBSCRIPTIONS MANAGEMENT
# =============================================================================

class SubscriptionCreateRequest(BaseModel):
    webhook_url: str


class SubscriptionDeleteRequest(BaseModel):
    subscription_id: str


@app.get('/api/kick/subscriptions')
async def api_list_subscriptions(request: Request):
    """Lista assinaturas de eventos da Kick.

    Retorna todas as assinaturas do canal.
    Requer acesso localhost.
    """
    _require_localhost(request)
    from .kick_subscriptions import get_subscriptions
    from .ngrok_manager import get_webhook_public_url

    subs = get_subscriptions()
    webhook_url = get_webhook_public_url()

    # Lista assinaturas
    result = await subs.list()

    # Se falhou, retorna erro detalhado
    if not result.success:
        return {
            'ok': False,
            'error': result.error,
            'message': result.message,
            'subscriptions': [],
            'chat_subscription': None,
            'has_chat_subscription': False,
            'ngrok_url': webhook_url,
        }

    subscriptions = result.subscriptions

    # Encontra assinatura de chat.message.sent
    chat_sub = None
    for s in subscriptions:
        if s.name == 'chat.message.sent':
            if not webhook_url or not s.webhook_url or s.webhook_url == webhook_url:
                chat_sub = s
                break

    STATE.kick_subscription_state = {
        'subscription_registered': chat_sub is not None,
        'subscription_id': chat_sub.id if chat_sub else '',
        'subscription_name': chat_sub.name if chat_sub else '',
        'subscription_status': chat_sub.status if chat_sub else '',
    }
    return {
        'ok': True,
        'subscriptions': [
            {
                'id': s.id,
                'name': s.name,
                'version': s.version,
                'status': s.status,
                'webhook_url': s.webhook_url,
                'created_at': s.created_at,
            }
            for s in subscriptions
        ],
        'chat_subscription': (
            {
                'id': chat_sub.id,
                'name': chat_sub.name,
                'status': chat_sub.status,
                'webhook_url': chat_sub.webhook_url,
            }
            if chat_sub else None
        ),
        'has_chat_subscription': chat_sub is not None,
        'ngrok_url': webhook_url,
    }


@app.post('/api/kick/subscriptions/create')
async def api_create_subscription(request: Request, req: SubscriptionCreateRequest):
    """Cria assinatura de chat.message.sent.

    Requer ngrok configurado e OAuth com escopo events:subscribe.
    Requer acesso localhost.
    """
    _require_localhost(request)
    from .kick_subscriptions import get_subscriptions
    from .ngrok_manager import get_webhook_public_url, is_ngrok_connected

    # Verifica ngrok
    if not is_ngrok_connected():
        return {
            'ok': False,
            'error': 'ngrok_not_connected',
            'message': 'Configure o ngrok primeiro',
        }

    # Verifica URL
    expected_url = get_webhook_public_url()
    if expected_url and req.webhook_url != expected_url:
        return {
            'ok': False,
            'error': 'url_mismatch',
            'message': f'URL deve ser {expected_url}',
        }

    subs = get_subscriptions()

    # Verifica se já existe
    existing = await subs.find_chat_message_subscription(req.webhook_url)
    if existing:
        return {
            'ok': True,
            'already_exists': True,
            'subscription_id': existing.id,
            'message': 'Assinatura já existe',
        }

    # Cria assinatura
    result = await subs.create(webhook_url=req.webhook_url)

    if result.success:
        return {
            'ok': True,
            'already_exists': False,
            'subscription_id': result.subscription.id if result.subscription else '',
            'message': result.message,
        }
    else:
        return {
            'ok': False,
            'error': result.error,
            'message': result.message,
        }


@app.post('/api/kick/subscriptions/delete')
async def api_delete_subscription(request: Request, req: SubscriptionDeleteRequest):
    """Cancela uma assinatura de evento.

    Requer confirmação explícita.
    Requer acesso localhost.
    """
    _require_localhost(request)
    from .kick_subscriptions import get_subscriptions

    if not req.subscription_id:
        return {
            'ok': False,
            'error': 'missing_id',
            'message': 'subscription_id é obrigatório',
        }

    subs = get_subscriptions()
    result = await subs.delete(req.subscription_id)

    if result.success:
        return {
            'ok': True,
            'message': result.message,
        }
    else:
        return {
            'ok': False,
            'error': result.error,
            'message': result.message,
        }


@app.get('/api/kick/webhook/status')
async def api_kick_webhook_status(request: Request):
    """Retorna status completo do webhook e conexões Kick.

    Inclui:
    - Status OAuth
    - Status ngrok
    - Assinaturas
    - Último evento (se disponível)
    Requer acesso localhost.
    """
    _require_localhost(request)
    from .kick_subscriptions import get_subscriptions
    from .ngrok_manager import get_webhook_public_url, is_ngrok_connected
    from .kick_chat_auth import get_kick_auth

    subs = get_subscriptions()
    auth = get_kick_auth()
    auth_status = auth.get_status()
    ngrok_url = get_webhook_public_url()
    ngrok_connected = is_ngrok_connected()

    # Lista assinaturas
    list_result = await subs.list()

    # Verifica assinatura de chat.message.sent
    chat_sub = None
    subscriptions_error = None
    if list_result.success:
        for s in list_result.subscriptions:
            if s.name == 'chat.message.sent':
                if not ngrok_url or s.webhook_url == ngrok_url:
                    chat_sub = s
                    break
    else:
        subscriptions_error = list_result.error
        subscriptions_error_message = list_result.message

    # Status do chat (baseado em conexão e assinatura)
    # IMPORTANTE: assinatura criada não significa chat operacional
    # Também requer webhook configurado na Kick e eventos recebidos
    chat_operational = False
    if (
        auth_status.is_authenticated
        and auth_status.has_required_scopes
        and ngrok_connected
        and chat_sub is not None
        and chat_sub.status == 'active'
    ):
        # Precisa receber eventos reais para ser operacional
        chat_operational = True

    return {
        'oauth': {
            'authenticated': auth_status.is_authenticated,
            'token_valid': auth_status.token_valid,
            'is_user_token': auth_status.is_user_token,
            'has_required_scopes': auth_status.has_required_scopes,
            'has_events_subscribe': auth_status.has_events_subscribe,
            'broadcaster_user_id': auth_status.broadcaster_user_id,
        },
        'ngrok': {
            'connected': ngrok_connected,
            'url': ngrok_url,
            'webhook_local_url': 'http://127.0.0.1:8766/api/webhooks/kick',
        },
        'subscription': {
            'exists': chat_sub is not None,
            'id': chat_sub.id if chat_sub else '',
            'status': chat_sub.status if chat_sub else '',
            'webhook_url': chat_sub.webhook_url if chat_sub else '',
        },
        'subscriptions_error': subscriptions_error,
        'subscriptions_error_message': subscriptions_error_message if not list_result.success else None,
        'chat_operational': chat_operational,
        'message': (
            'Chat operacional' if chat_operational
            else 'Configure OAuth, ngrok e assinatura'
        ),
    }


@app.get('/api/kick/connection/status')
async def api_kick_connection_status(request: Request):
    """Retorna status detalhado da conexão Kick via OAuth.

    Diferencia:
    - Não autenticado
    - Token expirado/inválido
    - App Token (não serve)
    - Escopos insuficientes
    - Canal identificado
    - Pronto para conectar
    Requer acesso localhost.
    """
    _require_localhost(request)
    from .kick_chat_auth import get_kick_auth

    auth = get_kick_auth()
    status = auth.get_status()

    return {
        'status': status.status,
        'is_authenticated': status.is_authenticated,
        'is_channel_identified': status.is_channel_identified,
        'is_ready': status.is_ready,
        'token_valid': status.token_valid,
        'is_user_token': status.is_user_token,
        'has_required_scopes': status.has_required_scopes,
        'has_events_subscribe': status.has_events_subscribe,
        'missing_scopes': status.missing_scopes,
        'user_id': status.user_id,
        'username': status.username,
        'channel_slug': status.channel_slug,
        'broadcaster_user_id': status.broadcaster_user_id,
        'expires_in_seconds': status.expires_in_seconds,
        'message': status.message,
        'chat_connected': STATE.kick_connected,
        'chat_channel': STATE.kick_channel,
    }


# ==============================================================================
# 🎁 API DO SORTEIO
# ==============================================================================
class StartRequest(BaseModel):
    keyword: str = ''


class DrawRequest(BaseModel):
    award: str = ''


@app.post('/api/giveaway/start')
async def api_giveaway_start(req: StartRequest):
    try:
        result = await giveaway.start(req.keyword)
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception('Falha ao iniciar sorteio')
        raise HTTPException(500, f'Falha: {e!r}')


@app.post('/api/giveaway/pause')
async def api_giveaway_pause():
    try:
        return await giveaway.pause()
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post('/api/giveaway/resume')
async def api_giveaway_resume():
    try:
        return await giveaway.resume()
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post('/api/giveaway/stop')
async def api_giveaway_stop():
    try:
        return await giveaway.stop()
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post('/api/giveaway/reset')
async def api_giveaway_reset():
    try:
        return await giveaway.reset()
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post('/api/giveaway/draw')
async def api_giveaway_draw(req: DrawRequest):
    try:
        return await giveaway.draw(req.award)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception('Falha ao sortear')
        raise HTTPException(500, f'Falha: {e!r}')


@app.post('/api/giveaway/answer')
async def api_giveaway_answer():
    try:
        return await giveaway.answer()
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post('/api/giveaway/skip')
async def api_giveaway_skip():
    try:
        return await giveaway.skip()
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get('/api/giveaway/chances')
async def api_giveaway_chances():
    """Retorna chances de cada participante (aba Chances)."""
    return {'participants': giveaway.compute_chances()}


class ParticipantToggleRequest(BaseModel):
    platform: Literal['twitch', 'kick', 'sim']
    username: str = Field(min_length=1, max_length=80)


@app.post('/api/giveaway/participants/toggle')
async def api_giveaway_participant_toggle(req: ParticipantToggleRequest, request: Request):
    """Alterna elegibilidade sem apagar a inscrição nem mudar as chances dos demais."""
    _require_localhost(request)
    key = f'{req.platform}:{req.username.strip().casefold()}'
    participant = STATE.participants.get(key)
    if participant is None:
        raise HTTPException(404, 'Participante não encontrado. Atualize a lista.')
    current = STATE.current_winner
    if current and current.platform == participant.platform and current.username.casefold() == participant.username.casefold():
        raise HTTPException(409, 'Este é o vencedor atual. Finalize ou pule o vencedor antes de alterar sua participação.')
    participant.active = not participant.active
    participant.active_changed_at = time.time()
    status = 'reativado' if participant.active else 'desativado'
    log(f'👤 {participant.username} ({participant.platform}) {status} manualmente para o sorteio.')
    await db.audit_add('admin', 'participant_reactivated' if participant.active else 'participant_disabled',
                       {'platform': participant.platform, 'username': participant.username})
    await _notify_state()
    return {'ok': True, 'platform': participant.platform, 'username': participant.username,
            'active': participant.active, 'active_changed_at': participant.active_changed_at}


@app.get('/api/giveaway/winners')
async def api_giveaway_winners(limit: int = 50):
    """Histórico de vencedores do sorteio atual."""
    return {'winners': [_serialize_winner(w) for w in STATE.winners[-limit:]]}


def _serialize_winner(w) -> dict:
    return {
        'username': w.username,
        'platform': w.platform,
        'user_id': w.user_id,
        'weight': w.weight,
        'chance_pct': w.chance_pct,
        'award': w.award,
        'drawn_at': w.drawn_at,
        'answered': w.answered,
        'responded_at': getattr(w, 'responded_at', None),
        'delivered': w.delivered,
    }


class PermissionsRequest(BaseModel):
    allow_viewers: bool = True
    allow_subs: bool = True
    allow_vips: bool = True
    allow_mods: bool = False
    platform_mods: dict[Literal['twitch','kick'], bool] | None = None
    entry_open_twitch: bool = True
    entry_open_kick: bool = True
    block_repeat_winner: bool = False


class TimerRequest(BaseModel):
    seconds: int = 60


class GiveawayAdvanceRequest(BaseModel):
    enabled: bool


class GroupWeights(BaseModel):
    sub: float = Field(ge=1,le=1000001,allow_inf_nan=False)
    vip: float = Field(ge=1,le=1000001,allow_inf_nan=False)

    mod: float = Field(default=1,ge=1,le=1000001,allow_inf_nan=False)

    @field_validator('sub','vip','mod',mode='before')
    @classmethod
    def decimal_comma(cls,value):
        return value.strip().replace(',','.') if isinstance(value,str) else value


class WeightsRequest(BaseModel):
    twitch: GroupWeights
    kick: GroupWeights


@app.post('/api/giveaway/weights')
async def api_giveaway_weights(req: WeightsRequest):
    async with STATE.lock:
        STATE.multipliers={platform:{'sub':weights.sub-1,'vip':weights.vip-1,'mod':weights.mod-1}
            for platform,weights in [('twitch',req.twitch),('kick',req.kick)]}
        for participant in STATE.participants.values():
            participant.weight=participant_weight(participant.platform,participant.is_sub,participant.is_vip,participant.is_mod)
        await db.config_set('permissions',{'allow_viewers':STATE.allow_viewers,'allow_subs':STATE.allow_subs,
            'allow_vips':STATE.allow_vips,'allow_mods':STATE.allow_mods,'platform_mods':STATE.platform_mods,'multipliers':STATE.multipliers})
    await _notify_state()
    return {'ok':True}


class CustomGiveawayPrizeRequest(BaseModel):
    name: str = Field(min_length=1,max_length=200)


class SelectGiveawayPrizeRequest(BaseModel):
    id: str = Field(min_length=1,max_length=100)


@app.post('/api/giveaway/prizes')
async def api_giveaway_prize_add(req: CustomGiveawayPrizeRequest):
    name=req.name.strip()
    if not name:raise HTTPException(422,'Informe o nome do prêmio.')
    async with STATE.lock:
        if len(STATE.custom_giveaway_prizes)>=500:raise HTTPException(400,'Limite de 500 prêmios personalizados.')
        prize=await giveaway_prizes.add(name)
    await _notify_state()
    return {'ok':True,'prize':prize}


@app.delete('/api/giveaway/prizes/{prize_id}')
async def api_giveaway_prize_delete(prize_id:str):
    try:
        async with STATE.lock:await giveaway_prizes.remove(prize_id)
    except ValueError as error:raise HTTPException(403,str(error))
    except LookupError as error:raise HTTPException(404,str(error))
    await _notify_state()
    return {'ok':True}


@app.post('/api/giveaway/prize/select')
async def api_giveaway_prize_select(req:SelectGiveawayPrizeRequest):
    try:
        async with STATE.lock:prize=await giveaway_prizes.select(req.id)
    except LookupError as error:raise HTTPException(404,str(error))
    await _notify_state()
    results=await chat.announce('next_prize',premio=prize['name'])
    return {'ok':True,'prize':prize,'announcements':results}


@app.post('/api/giveaway/auto-advance')
async def api_giveaway_auto_advance(req: GiveawayAdvanceRequest):
    STATE.auto_advance_timeout = req.enabled
    await db.config_set('auto_advance_timeout',req.enabled)
    await _notify_state()
    return {'ok':True}


@app.post('/api/giveaway/next')
async def api_giveaway_next(req: DrawRequest):
    try:
        if STATE.current_winner:
            return await giveaway.skip(award=req.award)
        return await giveaway.draw(req.award)
    except ValueError as error:
        raise HTTPException(400,str(error))


class AntibotRequest(BaseModel):
    enabled: bool = False
    types: dict[str, bool] = {'math': True, 'word': True, 'code': True}
    timer: int = 30
    random_chance: int = Field(default=50, ge=0, le=100)
    max_attempts: int = Field(default=3, ge=0, le=100)
    waive_subs_vips: bool = True
    send_to_chat: bool = False


@app.post('/api/antibot/config')
async def api_antibot_config(req: AntibotRequest):
    """Atualiza configurações do anti-bot."""
    if set(req.types) - {'math', 'word', 'code'}:
        raise HTTPException(422, 'Tipo de desafio desconhecido')
    if req.enabled and not any(req.types.values()):
        raise HTTPException(422, 'Ative ao menos um tipo de desafio')
    STATE.antibot_enabled = req.enabled
    STATE.antibot_types = req.types
    STATE.antibot_timer_seconds = STATE.winner_timer_seconds
    STATE.antibot_random_chance = max(0, min(100, req.random_chance))
    STATE.antibot_max_attempts = req.max_attempts
    STATE.captcha_waive_subs_vips = req.waive_subs_vips
    STATE.captcha_send_to_chat = req.send_to_chat
    STATE.chat_events['captcha_challenge'] = req.send_to_chat
    await db.config_set('chat_events',STATE.chat_events)
    await db.config_set('antibot', {
        'enabled': STATE.antibot_enabled,
        'types': STATE.antibot_types,
        'timer': STATE.antibot_timer_seconds,
        'selection_mode': 'entry',
        'random_chance': STATE.antibot_random_chance,
        'max_attempts': STATE.antibot_max_attempts,
        'waive_subs_vips': STATE.captcha_waive_subs_vips,
        'send_to_chat': STATE.captcha_send_to_chat,
    })
    await db.audit_add('admin', 'antibot_config', {
        'enabled': STATE.antibot_enabled,
        'types': STATE.antibot_types,
        'timer': STATE.antibot_timer_seconds,
        'random_chance': STATE.antibot_random_chance,
        'selection_mode': 'entry',
        'send_to_chat': STATE.captcha_send_to_chat,
    })
    await _notify_state()
    return {'ok': True}


class CaptchaAnswerRequest(BaseModel):
    answer: str


@app.post('/api/giveaway/captcha/answer')
async def api_captcha_answer(req: CaptchaAnswerRequest):
    """Valida resposta do captcha (manualmente, pelo admin)."""
    if STATE.antibot_challenge is None:
        raise HTTPException(400, 'Não há captcha em andamento')
    if STATE.current_winner is None:
        raise HTTPException(400, 'Não há vencedor ativo')

    result = await giveaway.submit_captcha(req.answer)
    if result['ok']:
        return result
    if result['status'] == 'expired':
        return {'ok': False, 'status': 'expired', 'detail': 'Captcha expirado'}
    if result['status'] == 'wrong':
        if result.get('exhausted'):
            return {**result,'detail':f"Tentativas esgotadas. Resposta correta: {result['expected']}. Escolha confirmar, gerar novo código ou pular."}
        limit=result['max_attempts'] or '∞'
        return {**result,'detail':f"Resposta incorreta ({result['attempts']}/{limit}). Tente novamente."}
    return result


@app.post('/api/giveaway/captcha/reissue')
async def api_captcha_reissue():
    """Emite novo captcha (regenera com outro tipo)."""
    if STATE.current_winner is None:
        raise HTTPException(400, 'Não há vencedor ativo')
    winner=STATE.current_winner
    if not winner.captcha_required or not winner.presence_confirmed:
        raise HTTPException(400, 'O vencedor precisa responder no chat antes de receber o código.')
    new_challenge = antibot.issue(platform=winner.platform, timed=False)
    winner.challenge = new_challenge['question']
    winner.captcha_text = new_challenge['question']
    winner.captcha_failed = False
    winner.outcome = 'captcha_pending'
    STATE.captcha_feedback = None
    STATE.winner_deadline = 0.0
    db_id=getattr(winner,'db_id',None)
    if db_id:
        await db.winner_update(db_id,captcha_text=winner.captcha_text,outcome=winner.outcome)
    await _notify_state()
    return {'ok': True, 'challenge': antibot.status_full()}


@app.get('/api/giveaway/captcha/full')
async def api_captcha_full():
    """Retorna o challenge COM a resposta esperada (só pro admin)."""
    return antibot.status_full() or {}


@app.post('/api/giveaway/timer')
async def api_giveaway_timer(req: TimerRequest):
    """Define o tempo (em segundos) que o vencedor tem pra responder."""
    seconds = max(10, min(600, int(req.seconds)))
    STATE.winner_timer_seconds = seconds
    STATE.antibot_timer_seconds = seconds
    await db.config_set('winner_timer_seconds', seconds)
    await _notify_state()
    return {'ok': True, 'timer': seconds}


class DebugInjectRequest(BaseModel):
    platform: str = 'twitch'
    username: str
    is_sub: bool = False
    is_vip: bool = False
    is_mod: bool = False


@app.post('/api/_debug/inject')
async def api_debug_inject(req: DebugInjectRequest):
    """Injeta participante direto (só pra teste quando o simulador não dispara keyword)."""
    if not STATE.simulation_mode:
        raise HTTPException(403, 'Só disponível em modo simulação')
    added = add_participant(
        platform=req.platform, username=req.username,
        is_sub=req.is_sub, is_vip=req.is_vip, is_mod=req.is_mod,
        weight=participant_weight(req.platform,req.is_sub,req.is_vip,req.is_mod),
    )
    await db.audit_add('admin', 'debug_inject', {
        'username': req.username, 'platform': req.platform,
        'is_sub': req.is_sub, 'is_vip': req.is_vip, 'is_mod': req.is_mod,
    })
    await _notify_state()
    return {'ok': True, 'added': added}


@app.post('/api/permissions')
async def api_permissions(req: PermissionsRequest):
    """Atualiza regras de permissão do sorteio."""
    fields=req.model_fields_set
    async with STATE.lock:
        for name in ['allow_viewers','allow_subs','allow_vips','allow_mods','block_repeat_winner']:
            if name in fields:setattr(STATE,name,getattr(req,name))
        if 'platform_mods' in fields:
            STATE.platform_mods={platform:(req.platform_mods or {}).get(platform,STATE.platform_mods.get(platform,STATE.allow_mods)) for platform in ['twitch','kick']}
        elif 'allow_mods' in fields:
            STATE.platform_mods={}
        for platform in ['twitch','kick']:
            key='entry_open_'+platform
            if key in fields:setattr(STATE,'accept_entries_'+platform,getattr(req,key))
            setattr(STATE,key,STATE.is_running and getattr(STATE,'accept_entries_'+platform))
        await db.config_set('entry_preferences',{'twitch':STATE.accept_entries_twitch,'kick':STATE.accept_entries_kick})
        await db.config_set('block_repeat_winner', STATE.block_repeat_winner)
        await db.config_set('permissions', {'allow_viewers': STATE.allow_viewers, 'allow_subs': STATE.allow_subs,
            'allow_vips': STATE.allow_vips, 'allow_mods': STATE.allow_mods, 'platform_mods': STATE.platform_mods, 'multipliers': STATE.multipliers})
        await db.audit_add('admin', 'permissions_changed', {**req.model_dump(exclude_unset=True),
            'entry_preferences':{'twitch':STATE.accept_entries_twitch,'kick':STATE.accept_entries_kick}})
    await _notify_state()
    return {'ok': True}


# ==============================================================================
# 🔑 TWITCH HELIX (credenciais pra API)
# ==============================================================================
class TwitchHelixRequest(BaseModel):
    client_id: str
    oauth: str = ''
    channel: str | None = None


@app.post('/api/twitch/helix/save')
async def api_twitch_helix_save(req: TwitchHelixRequest):
    """Uma credencial para leitura, envio manual, anúncios e avatares."""
    previous = (STATE.bot_twitch_client_id, STATE.bot_twitch_oauth, STATE.twitch_channel)
    STATE.bot_twitch_client_id = req.client_id.strip() or STATE.bot_twitch_client_id
    # aceita tanto 'oauth:xxx' quanto 'xxx'
    from .twitch_api import normalize_token
    oauth = normalize_token(req.oauth or STATE.bot_twitch_oauth)
    if oauth:oauth = 'oauth:'+oauth
    STATE.bot_twitch_oauth = oauth
    if req.channel is not None:
        STATE.twitch_channel = req.channel.strip().lstrip('#@').lower()
        await db.config_set('twitch_channel', STATE.twitch_channel)
    reconnect_required = previous != (STATE.bot_twitch_client_id, oauth, STATE.twitch_channel) and bool(chat.twitch.connected or chat.twitch._should_run)
    if reconnect_required:
        await chat.disconnect_twitch()
        STATE.twitch_connected = False
    chat.twitch.set_credentials(STATE.bot_twitch_client_id, oauth)
    # limpa cache pra forçar nova busca na próxima vez
    from . import twitch_api
    twitch_api.clear_cache()
    await db.config_set('bot_twitch_client_id', STATE.bot_twitch_client_id)
    await db.config_set('bot_twitch_oauth', STATE.bot_twitch_oauth)
    _sync_connection_env()
    await db.audit_add('admin', 'twitch_helix_saved', {
        'has_client_id': bool(STATE.bot_twitch_client_id),
        'has_oauth': bool(STATE.bot_twitch_oauth),
    })
    await _notify_state()
    return {'ok': True, 'reconnect_required': reconnect_required}


class TwitchTokenInspectRequest(BaseModel):
    oauth: str = Field(min_length=1,max_length=4096)


@app.post('/api/twitch/token/inspect')
async def api_twitch_token_inspect(req: TwitchTokenInspectRequest, request: Request):
    """Lê Client ID e escopos da Twitch sem salvar ou devolver o token."""
    _require_localhost(request)
    from . import twitch_api
    try:
        info = await twitch_api.validate_token('',req.oauth)
    except twitch_api.TokenValidationUnavailable as error:
        raise HTTPException(503,str(error)) from error
    if info is None:
        raise HTTPException(401,'A Twitch recusou este token. Copie o Access token, não o Refresh token, e confira se a autorização ainda está válida.')
    if not info.user_id:
        raise HTTPException(400,'Use um User Access Token, não um App Access Token.')
    return {'ok':True,'client_id':info.client_id,'login':info.login,'scopes':info.scopes,
            'has_read_chat':info.has_read_chat,'has_write_chat':info.has_write_chat,
            'expires_in':info.expires_in}


@app.post('/api/twitch/helix/test')
async def api_twitch_helix_test():
    """Testa as credenciais Helix validando o token diretamente.

    Usa https://id.twitch.tv/oauth2/validate para verificar:
    - Token válido (não expirado, não revogado)
    - Scope user:read:chat presente
    - User ID do token
    """
    from . import twitch_api
    from .twitch_chat import TokenInvalidError, ScopeMissingError

    if not STATE.bot_twitch_client_id or not STATE.bot_twitch_oauth:
        raise HTTPException(400, 'Falta Client-ID ou OAuth token')

    try:
        token_info = await twitch_api.validate_token(STATE.bot_twitch_client_id,STATE.bot_twitch_oauth)
    except twitch_api.TokenValidationUnavailable as error:
        raise HTTPException(503,str(error)) from error

    if token_info is None:
        raise HTTPException(401, 'Token inválido, expirado ou revogado')

    if token_info.client_id != STATE.bot_twitch_client_id:
        raise HTTPException(403, 'O Client-ID deve pertencer ao aplicativo que emitiu este token.')

    # Verifica scopes (user:read:chat é obrigatório para EventSub)
    missing = []
    if not token_info.has_read_chat:
        missing.append('user:read:chat')
    # user:write:chat é opcional mas queremos informar
    has_write = token_info.has_write_chat

    result = {
        'ok': True,
        'user_id': token_info.user_id,
        'scopes': token_info.scopes,
        'scope_count': len(token_info.scopes),
        'has_read_chat': token_info.has_read_chat,
        'has_write_chat': has_write,
    }

    if missing:
        msg = (f"Scopes ausentes: {', '.join(missing)}. "
               f"O token não conseguirá receber mensagens de chat via EventSub.")
        raise HTTPException(403, msg)

    return result

# ==============================================================================
# 🎰 ROLETA
# ==============================================================================
class RoletaItemRequest(BaseModel):
    id: int | None = None
    name: str = Field(min_length=1, max_length=100)
    weight: float = Field(default=1.0, ge=0, le=1000000, allow_inf_nan=False)
    active: bool = True
    icon: str = '🎁'


@app.get('/api/roleta/items')
async def api_roleta_items():
    """Retorna os valores salvos, sem substituir os pesos digitados."""
    items = [vars(item) for item in STATE.roleta_items]
    return {'items': items}


@app.post('/api/roleta/items')
async def api_roleta_items_save(req: RoletaItemRequest):
    """Salva o peso informado, sem alterar os demais prêmios."""
    new_id = await roleta.add_or_update_item(req.model_dump())
    await _notify_state()
    return {'ok': True, 'id': new_id}


class RoletaBulkRequest(BaseModel):
    items: list[RoletaItemRequest]


@app.post('/api/roleta/items/bulk')
async def api_roleta_items_bulk(req: RoletaBulkRequest):
    """Salva os pesos recebidos; a normalização ocorre apenas no sorteio."""
    if not req.items:
        raise HTTPException(400, 'Lista de itens vazia')
    for item in req.items:
        await roleta.add_or_update_item(item.model_dump())
    await _notify_state()
    return {'ok': True, 'count': len(req.items)}


@app.delete('/api/roleta/items/{item_id}')
async def api_roleta_items_delete(item_id: int):
    await roleta.delete_item(item_id)
    await _notify_state()
    return {'ok': True}


class RoletaSpinRequest(BaseModel):
    nick: str = ''
    test_mode: bool = False
    attempts: int = Field(default=1, ge=1, le=20)


@app.post('/api/roleta/spin')
async def api_roleta_spin(req: RoletaSpinRequest):
    """Gira a roleta e mostra o overlay.
    Se test_mode=False, exige nick não vazio."""
    if not req.test_mode and not req.nick.strip():
        raise HTTPException(400, 'Informe o nick da pessoa ou marque "Giro de teste"')
    if STATE.roleta_spinning or STATE.roleta_remaining:
        raise HTTPException(409, 'Já existe um giro ou sequência em andamento.')
    STATE.roleta_test_mode = req.test_mode
    STATE.roleta_total = req.attempts
    STATE.roleta_remaining = req.attempts - 1
    result = await roleta.spin(nick=req.nick.strip())
    if not result:
        STATE.roleta_remaining = 0
        raise HTTPException(400, 'Nenhum item ativo na roleta')
    await _notify_state()
    return result


class RoletaVisibleRequest(BaseModel):
    visible: bool


@app.post('/api/roleta/visible')
async def api_roleta_visible(req: RoletaVisibleRequest):
    await roleta.set_visible(req.visible)
    await _notify_state()
    return {'ok': True}


class RoletaFinishRequest(BaseModel):
    spin_id: int
    winner: str = ''


class RoletaAckStartRequest(BaseModel):
    spin_id: int


@app.post('/api/roleta/ack-start')
async def api_roleta_ack_start(req: RoletaAckStartRequest):
    """Chamado pelo overlay quando inicia a animação de um spin.
    Permite ao admin saber se o overlay realmente recebeu o comando."""
    if STATE.roleta_current_spin_id != req.spin_id:
        return {'ok': False, 'reason': 'stale spin_id'}
    STATE.roleta_last_ack = time.time()
    await _notify_state()
    return {'ok': True}


@app.post('/api/roleta/finished')
async def api_roleta_finished(req: RoletaFinishRequest):
    """Chamado pelo overlay quando a animação termina."""
    if STATE.roleta_current_spin_id != req.spin_id:
        return {'ok': False, 'reason': 'stale spin_id'}
    await roleta.mark_finished(winner=req.winner)
    await _notify_state()
    return {'ok': True}


class RoletaConfigRequest(BaseModel):
    duration_seconds: float = Field(default=4.5, ge=0.5, le=60, allow_inf_nan=False)
    extra_spins: int = Field(default=6, ge=0, le=20)
    auto_hide: bool = True
    equal_slices: bool = False
    result_seconds: float = Field(default=8, ge=1, le=120, allow_inf_nan=False)


@app.post('/api/roleta/config')
async def api_roleta_config(req: RoletaConfigRequest):
    """Atualiza duração da animação e voltas extras do giro."""
    duration = max(0.5, min(60.0, float(req.duration_seconds)))
    spins = max(0, min(20, int(req.extra_spins)))
    STATE.roleta_auto_hide = req.auto_hide
    STATE.roleta_equal_slices = req.equal_slices
    STATE.roleta_result_seconds = req.result_seconds
    await db.config_set('roleta_auto_hide', req.auto_hide)
    await db.config_set('roleta_equal_slices', req.equal_slices)
    await db.config_set('roleta_result_seconds', req.result_seconds)
    STATE.roleta_duration_seconds = duration
    STATE.roleta_extra_spins = spins
    await db.config_set('roleta_duration_seconds', str(duration))
    await db.config_set('roleta_extra_spins', str(spins))
    await _notify_state()
    return {'ok': True, 'duration_seconds': duration, 'extra_spins': spins}


class RoletaSettingsRequest(RoletaConfigRequest):
    items: list[RoletaItemRequest]
    announce_chat: bool


@app.post('/api/roleta/settings')
async def api_roleta_settings(req: RoletaSettingsRequest):
    """Salvar tudo: valida antes e persiste numa única transação."""
    from .state import RoletaItem
    async with STATE.lock:
        if STATE.roleta_spinning or STATE.roleta_remaining:
            raise HTTPException(409, 'Aguarde a sequência terminar antes de salvar a roleta.')
        if any(item.id is None for item in req.items):
            raise HTTPException(400, 'Adicione o prêmio antes de salvar.')
        items = [RoletaItem(
            id=item.id, name=item.name, weight=item.weight,
            active=item.active, icon=item.icon) for item in req.items]
        events = {**STATE.chat_events, 'prize_won': req.announce_chat}
        config = {'roleta_duration_seconds': str(req.duration_seconds),
                  'roleta_extra_spins': str(req.extra_spins),
                  'roleta_auto_hide': req.auto_hide,
                  'roleta_equal_slices': req.equal_slices,
                  'roleta_result_seconds': req.result_seconds,
                  'chat_events': events}
        try:
            await db.roleta_save_settings([vars(item) for item in items], config)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        STATE.roleta_items = items
        STATE.roleta_duration_seconds = req.duration_seconds
        STATE.roleta_extra_spins = req.extra_spins
        STATE.roleta_auto_hide = req.auto_hide
        STATE.roleta_equal_slices = req.equal_slices
        STATE.roleta_result_seconds = req.result_seconds
        STATE.chat_events = events
    await _notify_state()
    return {'ok': True, 'count': len(items), 'items': [vars(item) for item in items]}


@app.get('/api/roleta/history')
async def api_roleta_history(limit: int = 50):
    rows = await db.roleta_history_list(limit=limit)
    return {'history': rows}


# ==============================================================================
# 📜 HISTÓRICO PERSISTENTE
# ==============================================================================
@app.get('/api/history')
async def api_history(section: str = 'winners', limit: int = 100,
                      username: str = '', since: float = 0):
    """Histórico unificado. section: winners|roleta|audit.
    - winners: filtro por username e por timestamp `since`.
    - roleta: filtro por timestamp.
    - audit: aceita filtro por username (no payload) e timestamp.
    """
    rows: list[dict] = []
    if section == 'winners':
        rows = await db.winners_list(limit=limit, username=username or None)
        if since:
            rows = [w for w in rows if (w.get('drawn_at') or 0) >= since]
    elif section == 'roleta':
        rows = await db.roleta_history_list(limit=limit)
        if since:
            rows = [h for h in rows if (h.get('ts') or 0) >= since]
    elif section == 'audit':
        rows = await db.audit_list(limit=limit)
        if since:
            rows = [e for e in rows if (e.get('ts') or 0) >= since]
        if username:
            u = username.lower()
            rows = [e for e in rows
                    if u in (e.get('actor', '').lower())
                    or u in json.dumps(e.get('payload', {})).lower()]
    return {'rows': rows, 'count': len(rows)}


@app.get('/api/export/roleta.csv')
async def api_export_roleta():
    rows = await db.roleta_history_list(limit=10000)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['ts_human', 'winner', 'prize', 'spin_index'])
    for r in rows:
        ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r.get('ts', 0)))
        w.writerow([ts, r.get('winner', ''), r.get('prize', ''), r.get('spin_index', '')])
    return Response(
        content=out.getvalue(),
        media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=roleta_history.csv'},
    )


# ==============================================================================
# 📊 AUDITORIA / ANALYTICS / EXPORT
# ==============================================================================
@app.get('/api/audit/list')
async def api_audit_list(limit: int = 200, action: str = ''):
    """Lista eventos de auditoria (mais recentes primeiro)."""
    rows = await analytics.audit_list(limit=limit, action_filter=action)
    return {'events': rows, 'count': len(rows)}


@app.get('/api/fairness/report')
async def api_fairness_report():
    """Relatório de fairness do sorteio atual + histórico."""
    return await analytics.fairness_report()


@app.get('/api/export/participants.csv')
async def api_export_participants():
    """Exporta participantes da sessão atual em CSV."""
    csv = await analytics.export_participants_csv()
    return Response(
        content=csv,
        media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename="participantes.csv"'},
    )


@app.get('/api/export/winners.csv')
async def api_export_winners():
    """Exporta histórico de vencedores em CSV."""
    csv = await analytics.export_winners_csv()
    return Response(
        content=csv,
        media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename="vencedores.csv"'},
    )


@app.get('/api/export/audit.csv')
async def api_export_audit():
    """Exporta audit log em CSV."""
    csv = await analytics.export_audit_csv()
    return Response(
        content=csv,
        media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename="auditoria.csv"'},
    )


# ==============================================================================
# 🏁 START
# ==============================================================================


class AppearanceRequest(BaseModel):
    primary_color: str = Field(default='#79e8a4', pattern=r'^#[0-9a-fA-F]{6}$')
    accent_color: str = Field(default='#c060ff', pattern=r'^#[0-9a-fA-F]{6}$')
    bg_color: str = Field(default='#0b0e18', pattern=r'^#[0-9a-fA-F]{6}$')
    wheel_gold: str = Field(default='#d4af63', pattern=r'^#[0-9a-fA-F]{6}$')
    wheel_dark: str = Field(default='#1b242c', pattern=r'^#[0-9a-fA-F]{6}$')
    wheel_size: int = Field(default=760, ge=360, le=1000)
    winner_font_size: int = Field(default=48, ge=24, le=100)
    winner_animation: str = Field(default='classic', pattern=r'^(classic|spotlight|rise|flip|burst|random)$')
    draw_animation: str = Field(default='roulette', pattern=r'^(roulette|slots|countdown|cards|dice|radar|chest|particles|portal|spotlights|random|none)$')
    draw_animation_seconds: int = Field(default=4, ge=2, le=10)
    overlay_font: str = Field(default='Georgia', pattern=r'^(Georgia|Segoe UI|Trebuchet MS)$')
    show_prize_list: bool = True
    show_chances_overlay: bool = False


@app.post('/api/appearance')
async def api_appearance(req: AppearanceRequest):
    STATE.appearance = req.model_dump()
    await db.config_set('appearance', STATE.appearance)
    await _notify_state()
    return {'ok': True}


class ChatSettingsRequest(BaseModel):
    twitch_enabled: bool = False
    kick_enabled: bool = False
    events: dict[str, bool] = Field(default_factory=dict)
    templates: dict[str, dict[str, str]] = Field(default_factory=dict)
    destinations: dict[str, dict[str,bool]] = Field(default_factory=dict)


class ViewerCommandsRequest(BaseModel):
    skip_enabled: bool = True
    skip_command: str = Field(default='!pular', pattern=r'^![A-Za-z][A-Za-z0-9_]{0,23}$')
    skip_limit: int = Field(default=3, ge=1, le=100)
    nick_enabled: bool = True
    nick_command: str = Field(default='!nick', pattern=r'^![A-Za-z][A-Za-z0-9_]{0,23}$')
    rank_enabled: bool = True
    rank_command: str = Field(default='!rank', pattern=r'^![A-Za-z][A-Za-z0-9_]{0,23}$')


@app.post('/api/chat/commands/config')
async def api_viewer_commands(req: ViewerCommandsRequest):
    reserved = {STATE.keyword.casefold(), '!roleta'}
    chosen = {req.skip_command.casefold(), req.nick_command.casefold(), req.rank_command.casefold()}
    if len(chosen) != 3 or chosen & reserved:
        raise HTTPException(400, 'Comando já usado pelo sorteio ou por outra função.')
    STATE.skip_chat_enabled = req.skip_enabled
    STATE.skip_chat_command = req.skip_command.lower()
    STATE.skip_chat_limit = req.skip_limit
    STATE.nick_lookup_enabled = req.nick_enabled
    STATE.nick_lookup_command = req.nick_command.lower()
    STATE.rank_lookup_enabled = req.rank_enabled
    STATE.rank_lookup_command = req.rank_command.lower()
    await db.config_set('viewer_commands', {
        'skip_enabled': STATE.skip_chat_enabled,
        'skip_command': STATE.skip_chat_command,
        'skip_limit': STATE.skip_chat_limit,
        'nick_enabled': STATE.nick_lookup_enabled,
        'nick_command': STATE.nick_lookup_command,
        'rank_enabled': STATE.rank_lookup_enabled,
        'rank_command': STATE.rank_lookup_command,
    })
    await _notify_state()
    return {'ok': True, **full_state()['viewer_commands']}


@app.post('/api/bots/settings')
async def api_bot_settings(req: ChatSettingsRequest):
    import string
    allowed = {'nome', 'plataforma', 'premio', 'keyword', 'tempo', 'desafio', 'chance', 'peso', 'participantes', 'proximo',
               'tentativa', 'restantes',
               'comando', 'comando_nick', 'usos', 'limite', 'nick', 'resultado', 'motivo',
               'total', 'respondeu', 'mamou', 'desistiu', 'pulou', 'pendente'}
    for event, platforms in req.templates.items():
        if event not in STATE.message_templates:
            raise HTTPException(400, 'Evento desconhecido')
        for platform, template in platforms.items():
            if platform not in ('twitch', 'kick') or len(template) > 400:
                raise HTTPException(400, 'Mensagem ou plataforma inválida')
            try:
                fields = list(string.Formatter().parse(template))
                if any(name is not None and (name not in allowed or spec or conv)
                       for _, name, spec, conv in fields):
                    raise ValueError()
            except ValueError:
                raise HTTPException(400, 'Use apenas os campos indicados na tela')
    STATE.bot_twitch_enabled = req.twitch_enabled
    STATE.bot_kick_enabled = req.kick_enabled
    STATE.chat_events.update({k: v for k, v in req.events.items() if k in STATE.chat_events})
    for event, platforms in req.templates.items():
        from .state import _default_messages
        defaults = _default_messages().get(event, {})
        STATE.message_templates[event].update({platform: template.strip() or defaults.get(platform, '')
                                               for platform, template in platforms.items()})
    for event, platforms in req.destinations.items():
        if event in STATE.chat_events:
            STATE.chat_event_platforms[event]={p:v for p,v in platforms.items() if p in ('twitch','kick')}
    await db.config_set('chat_event_platforms',STATE.chat_event_platforms)
    if 'captcha_challenge' in req.events:
        STATE.captcha_send_to_chat=req.events['captcha_challenge']
        config=await db.config_get('antibot') or {}
        config['send_to_chat']=STATE.captcha_send_to_chat
        await db.config_set('antibot',config)
    await db.config_set('bots', {'twitch_enabled': req.twitch_enabled, 'kick_enabled': req.kick_enabled})
    await db.config_set('chat_silent_twitch', not req.twitch_enabled)
    await db.config_set('chat_silent_kick', not req.kick_enabled)
    _sync_connection_env()
    await db.config_set('chat_events', STATE.chat_events)
    await db.config_set('message_templates', STATE.message_templates)
    await _notify_state()
    return {'ok': True}


class ChatSendRequest(BaseModel):
    platform: Literal['twitch', 'kick']
    text: str = Field(min_length=1, max_length=400)


class PlatformAnnouncementsRequest(BaseModel):
    enabled: bool


class MegaMuConfigRequest(BaseModel):
    dv: str = Field(max_length=200)
    key: str = Field(default='',max_length=1000)
    enabled: bool = True


@app.post('/api/megamu/config')
async def api_megamu_config(req: MegaMuConfigRequest, request: Request):
    _require_localhost(request)
    saved=env_config.read()
    changed=(req.dv.strip() != saved.get('MEGAMU_DV','') or
             bool(req.key.strip() and req.key.strip()!=saved.get('MEGAMU_KEY','')))
    env_config.update({'MEGAMU_DV':req.dv.strip(), 'MEGAMU_KEY':req.key.strip() or saved.get('MEGAMU_KEY',''),
        'MEGAMU_ENABLED':str(req.enabled).lower()})
    STATE.megamu_updated_at=0
    if changed:
        STATE.megamu_awards=[]
        if STATE.selected_giveaway_prize and STATE.selected_giveaway_prize.get('source')=='megamu':
            STATE.selected_giveaway_prize=None
            await db.config_set('selected_giveaway_prize',None)
    STATE.megamu_error=''
    if req.enabled and req.dv.strip() and env_config.read().get('MEGAMU_KEY'):
        try: await megamu.refresh()
        except ValueError: pass  # configuração salva; diagnóstico visível no painel
    await _notify_state()
    return {'ok':True, **megamu.status()}


@app.get('/api/megamu/awards')
async def api_megamu_awards():
    try:
        result=await megamu.refresh()
        env_config.update({'MEGAMU_ENABLED':'true'})
        result=megamu.status()
        await _notify_state()
        return result
    except ValueError as error:
        await _notify_state()
        raise HTTPException(502,str(error))


@app.post('/api/megamu/import')
async def api_megamu_import(request: Request):
    _require_localhost(request)
    try: result=await megamu.refresh()
    except ValueError as error: raise HTTPException(502,str(error))
    async with STATE.lock:
        if STATE.roleta_spinning or STATE.roleta_remaining:
            raise HTTPException(409,'Espere os giros terminarem antes de adicionar prêmios.')
        existing={item.name.casefold() for item in STATE.roleta_items}
        added=0
        for award in result['awards']:
            if award['name'].casefold() in existing:continue
            await db.roleta_upsert({'name':award['name'],'weight':1,'active':True,'icon':'🎁'})
            existing.add(award['name'].casefold());added+=1
        await roleta.load_items_from_db()
    await _notify_state()
    return {'ok':True,'added':added}


@app.post('/api/bots/{platform}/announcements')
async def api_platform_announcements(platform: Literal['twitch', 'kick'], req: PlatformAnnouncementsRequest):
    setattr(STATE, 'bot_' + platform + '_enabled', req.enabled)
    await db.config_set('chat_silent_' + platform, not req.enabled)
    _sync_connection_env()
    await _notify_state()
    return {'ok': True}


@app.post('/api/chat/send')
async def api_chat_send(req: ChatSendRequest, request: Request):
    _require_localhost(request)
    if not req.text.strip():
        raise HTTPException(422, 'Digite uma mensagem')
    if STATE.simulation_mode:
        raise HTTPException(400, 'Conecte uma conta real para enviar mensagens')
    sent = await chat.send(req.platform, req.text.strip(), automatic=False)
    if not sent and req.platform=='kick':
        raise HTTPException(502,chat.kick.last_send_error or 'A Kick não confirmou o envio. Confira a conta autorizada e chat:write.')
    if not sent:
        raise HTTPException(502, chat.last_send_errors.get(req.platform) or 'Mensagem não enviada. Confira a conexão e a permissão de escrita da conta na aba Conexões.')
    return {'ok': True}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(
        'servidor.app:app',
        host='127.0.0.1',
        port=8777,
        log_level='info',
    )

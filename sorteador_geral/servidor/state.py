"""Estado global do Sorteador Geral.

Mantém em memória tudo que precisa ser compartilhado entre os módulos:
participantes, vencedores, configurações ativas, status das conexões,
e o log de atividades. A persistência em SQLite é feita pelo módulo
`db.py`, mas o estado vivo (que muda a cada mensagem) fica aqui.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


# ==============================================================================
# 📦 ENTIDADES
# ==============================================================================
def _default_messages() -> dict[str, dict[str, str]]:
    """Mensagens padrão do bot (por evento × plataforma).

    Eventos cobertos:
      - giveaway_open: ao iniciar
      - entry_accepted: ao aceitar inscrição (se habilitado)
      - entry_repeat: tentativa repetida
      - giveaway_paused
      - giveaway_resumed
      - giveaway_closed
      - winner_announced
      - winner_claim_instructions: confirmação do prêmio, orientação de !nick
      - winner_no_response
      - captcha_challenge
      - captcha_success
      - captcha_fail
      - prize_won (roleta)
      - rule_changed (mudança de multiplicador)
    """
    base = {
        'giveaway_open': {
            'twitch': '🎉 Sorteio aberto! Digite {keyword} para participar.',
            'kick': '🎉 Sorteio aberto! Digite {keyword} para participar.',
        },
        'entry_accepted': {
            'twitch': '✅ {nome}, inscrição confirmada! Chance: {peso}x.',
            'kick': '✅ {nome}, inscrição confirmada! Chance: {peso}x.',
        },
        'entry_repeat': {
            'twitch': 'ℹ️ {nome}, você já está participando! Chance: {peso}x.',
            'kick': 'ℹ️ {nome}, você já está participando! Chance: {peso}x.',
        },
        'giveaway_paused': {
            'twitch': '⏸️ Inscrições pausadas.',
            'kick': '⏸️ Inscrições pausadas.',
        },
        'giveaway_resumed': {
            'twitch': '▶️ Inscrições retomadas!',
            'kick': '▶️ Inscrições retomadas!',
        },
        'giveaway_closed': {
            'twitch': '🔒 Inscrições encerradas!',
            'kick': '🔒 Inscrições encerradas!',
        },
        'winner_announced': {
            'twitch': '🏆 Vencedor: {nome} ({plataforma})! Você tem {tempo}s para responder.',
            'kick': '🏆 Vencedor: {nome} ({plataforma})! Você tem {tempo}s para responder.',
        },
        'winner_claim_instructions': {
            'twitch': '🎁 @{nome}, envie {comando_nick} NomeDoPersonagem ou !NomeDoPersonagem para consultar e receber seu prêmio ({premio}).',
            'kick': '🎁 @{nome}, envie {comando_nick} NomeDoPersonagem ou !NomeDoPersonagem para consultar e receber seu prêmio ({premio}).',
        },
        'winner_no_response': {
            'twitch': '⏰ O prazo de {nome} acabou. {proximo}',
            'kick': '⏰ O prazo de {nome} acabou. {proximo}',
        },
        'captcha_challenge': {
            'twitch': '🛡️ {nome}, responda: {desafio}',
            'kick': '🛡️ {nome}, responda: {desafio}',
        },
        'captcha_success': {
            'twitch': '✅ Resposta correta, {nome}!',
            'kick': '✅ Resposta correta, {nome}!',
        },
        'captcha_retry': {
            'twitch': '❌ {nome}, resposta incorreta. Tentativa {tentativa}/{limite}. Tente novamente.',
            'kick': '❌ {nome}, resposta incorreta. Tentativa {tentativa}/{limite}. Tente novamente.',
        },
        'captcha_fail': {
            'twitch': '❌ Resposta incorreta, {nome}. A resposta certa era: {resposta}. Aguarde a decisão do organizador.',
            'kick': '❌ Resposta incorreta, {nome}. A resposta certa era: {resposta}. Aguarde a decisão do organizador.',
        },
        'prize_won': {
            'twitch': '🎁 {nome} ganhou: {premio}!',
            'kick': '🎁 {nome} ganhou: {premio}!',
        },
        'next_prize': {
            'twitch': '🎁 Próximo sorteio: {premio}',
            'kick': '🎁 Próximo sorteio: {premio}',
        },
        'winner_declined': {
            'twitch': '⏭️ {nome} desistiu do prêmio. {usos}/{limite} desistências usadas neste sorteio.',
            'kick': '⏭️ {nome} desistiu do prêmio. {usos}/{limite} desistências usadas neste sorteio.',
        },
        'winner_skip_limit': {
            'twitch': '⚠️ {nome}, o limite de {limite} desistências neste sorteio já foi atingido.',
            'kick': '⚠️ {nome}, o limite de {limite} desistências neste sorteio já foi atingido.',
        },
        'nick_lookup': {
            'twitch': '{resultado}',
            'kick': '{resultado}',
        },
        'nick_lookup_error': {
            'twitch': '❌ {nome}: {motivo}',
            'kick': '❌ {nome}: {motivo}',
        },
        'rank_lookup': {
            'twitch': '🏆 @{nick} já ganhou {total} vezes, respondeu {respondeu} e mamou {mamou}.',
            'kick': '🏆 @{nick} já ganhou {total} vezes, respondeu {respondeu} e mamou {mamou}.',
        },
        'rule_changed': {
            'twitch': 'ℹ️ Regras do sorteio foram atualizadas.',
            'kick': 'ℹ️ Regras do sorteio foram atualizadas.',
        },
    }
    return base


@dataclass
class Participant:
    """Um participante do sorteio."""
    platform: str          # 'twitch' ou 'kick' ou 'sim'
    username: str          # como aparece no chat
    user_id: str = ''      # ID estável da plataforma (Twitch user-id / Kick id)
    is_sub: bool = False
    is_vip: bool = False
    is_mod: bool = False
    is_owner: bool = False
    weight: float = 1.0    # multiplicador aplicado no momento da entrada
    first_seen: float = field(default_factory=time.time)
    message_count: int = 1
    is_winner: bool = False  # se já ganhou neste sorteio
    active: bool = True  # controle manual: desativado não entra no próximo sorteio
    active_changed_at: float = 0.0  # horário da última alteração pelo administrador
    avatar_url: str = ''  # URL da foto de perfil (Twitch API; vazio se sem token)
    captcha_marked: bool = False
    captcha_status: str = 'disabled'
    captcha_chance_at_entry: int = 0
    captcha_decided_at: float = 0.0


@dataclass
class Winner:
    """Um vencedor já sorteado."""
    platform: str
    username: str
    user_id: str
    weight: float
    chance_pct: float     # chance efetiva no momento do sorteio
    award: str
    drawn_at: float
    answered: bool = False
    outcome: str = 'pending'  # answered / timeout / declined / skipped / pending
    responded_at: float = 0.0
    captcha_required: bool = False  # após a primeira mensagem, solicita o desafio
    presence_confirmed: bool = False
    captcha_failed: bool = False
    captcha_text: str = ''
    captcha_passed: bool = False
    delivered: bool = False  # se o prêmio foi marcado como entregue
    is_sub: bool = False
    is_vip: bool = False
    is_mod: bool = False
    avatar_url: str = ''
    prize_id: str = ''


@dataclass
class RoletaItem:
    """Um prêmio da roleta."""
    id: int
    name: str
    weight: float
    active: bool = True
    icon: str = '🎁'


# ==============================================================================
# 🧠 ESTADO GLOBAL
# ==============================================================================
@dataclass
class AppState:
    """Estado vivo do aplicativo."""

    # ---- Sorteio ----
    is_running: bool = False
    is_paused: bool = False
    keyword: str = ''
    winner_timer_seconds: int = 60
    auto_advance_timeout: bool = False
    captcha_feedback: dict | None = None
    custom_giveaway_prizes: list[dict] = field(default_factory=list)
    selected_giveaway_prize: dict | None = None
    megamu_awards: list[dict] = field(default_factory=list)
    megamu_updated_at: float = 0.0
    megamu_error: str = ''
    allow_dual_entry: bool = False
    block_repeat_winner: bool = True
    participants: dict[str, Participant] = field(default_factory=dict)
    winners: list[Winner] = field(default_factory=list)
    current_winner: Winner | None = None
    winner_deadline: float = 0.0
    draw_reveal_until: float = 0.0  # suspense no OBS: ainda não revelar vencedor
    draw_animation_active: str = ''  # efeito resolvido para este sorteio (inclusive aleatório)
    status_message: str = 'Aguardando'
    accept_entries_twitch: bool = True
    accept_entries_kick: bool = True
    entry_open_twitch: bool = True
    entry_open_kick: bool = True
    skip_chat_enabled: bool = True
    skip_chat_command: str = '!pular'
    skip_chat_limit: int = 3  # total de desistências voluntárias por coleta
    skip_chat_uses: int = 0
    nick_lookup_enabled: bool = True
    nick_lookup_command: str = '!nick'
    rank_lookup_enabled: bool = True
    rank_lookup_command: str = '!rank'

    # ---- Permissões e multiplicadores ----
    allow_viewers: bool = True
    allow_subs: bool = True
    allow_vips: bool = True
    allow_mods: bool = False
    platform_mods: dict[str, bool] = field(default_factory=dict)
    # viewer_weight: float = 1.0  # futuro: personalizar peso de viewer
    multipliers: dict[str, dict[str, float]] = field(default_factory=lambda: {
        'twitch': {'sub': 2.0, 'vip': 2.0},
        'kick': {'sub': 2.0, 'vip': 2.0},
    })
    captcha_waive_subs_vips: bool = True

    # ---- Anti-bot ----
    antibot_enabled: bool = False
    antibot_types: dict[str, bool] = field(default_factory=lambda: {
        'math': True, 'word': True, 'code': True,
    })
    antibot_timer_seconds: int = 30
    antibot_random_chance: int = 50
    antibot_max_attempts: int = 3  # 0 = ilimitadas; vale por desafio
    antibot_challenge: dict[str, Any] | None = None
    captcha_send_to_chat: bool = False  # se True, o bot envia o desafio no chat

    # ---- Conexões ----
    twitch_channel: str = ''
    kick_channel: str = ''
    kick_receive_mode: str = 'direct'
    kick_receive_enabled: bool = False
    kick_channel_id: int | None = None
    kick_chatroom_id: int | None = None
    twitch_connected: bool = False
    kick_connected: bool = False
    simulation_mode: bool = True  # se true, não conecta de verdade

    # Conversas recentes em memória (não são gravadas no banco).
    chat_messages: deque = field(default_factory=lambda: deque(maxlen=300))
    winner_chat_messages: deque = field(default_factory=lambda: deque(maxlen=6))
    # O prêmio já foi confirmado e o cronômetro encerrou, mas o OBS aguarda
    # o nick do personagem. Não bloqueia o próximo sorteio.
    winner_claim_pending: Winner | None = None
    winner_claim_recent: Winner | None = None
    winner_claim_feedback: dict[str, Any] | None = None
    winner_claim_feedback_until: float = 0.0

    # ---- Bots / mensagens fixas ----
    bot_twitch_enabled: bool = False
    bot_kick_enabled: bool = False
    bot_twitch_oauth: str = ''
    bot_twitch_username: str = ''
    bot_twitch_client_id: str = ''  # Client-ID do app Twitch (pra buscar avatares)
    bot_kick_token: str = ''
    message_templates: dict[str, dict[str, str]] = field(default_factory=_default_messages)

    # ---- Roleta ----
    roleta_items: list[RoletaItem] = field(default_factory=list)
    roleta_visible: bool = False
    roleta_spinning: bool = False
    roleta_current_spin_id: int = 0
    roleta_last_ack: float = 0.0  # time.time() do último ack-start do overlay
    roleta_last_winner: str = ''
    roleta_last_prize: str = ''
    roleta_last_index: int = -1
    roleta_last_nick: str = ''
    roleta_history: list[dict] = field(default_factory=list)

    # ---- Snapshot do giro em andamento (capturado no spin, lido pelo overlay) ----
    # Mantém os items, duração e voltas EXATOS usados no sorteio, mesmo se a config
    # mudar ou items forem editados durante a animação. None quando não há giro.
    roleta_active_spin: dict | None = None

    # ---- Configuração do giro (persistida via config_get/set) ----
    roleta_duration_seconds: float = 4.5   # duração da animação CSS
    roleta_equal_slices: bool = False
    roleta_auto_hide: bool = True
    roleta_result_seconds: float = 8.0
    roleta_remaining: int = 0
    roleta_total: int = 1
    roleta_test_mode: bool = False
    chat_events: dict[str, bool] = field(default_factory=lambda: {
        'giveaway_open': True, 'giveaway_paused': True, 'giveaway_resumed': True,
        'giveaway_closed': True, 'winner_announced': True, 'winner_claim_instructions': True, 'prize_won': True,
        'entry_accepted': True, 'entry_repeat': True,
        'captcha_success': True, 'captcha_retry': True, 'captcha_fail': True, 'winner_no_response': True,
        'captcha_challenge': False,
        'next_prize': True,
        'winner_declined': True, 'winner_skip_limit': True,
        'nick_lookup': True, 'nick_lookup_error': True,
        'rank_lookup': True,
    })
    chat_event_platforms: dict = field(default_factory=dict)
    roleta_extra_spins: int = 6            # voltas extras antes de parar

    # ---- Aparência ----
    appearance: dict[str, Any] = field(default_factory=lambda: {
        'wheel_gold': '#d4af63',
        'wheel_dark': '#1b242c',
        'wheel_size': 760,
        'show_prize_list': True,
        'overlay_font': 'Georgia',
        'primary_color': '#79e8a4',
        'accent_color': '#c060ff',
        'bg_color': '#0a0a18',
        'winner_font_size': 48,
        'winner_animation': 'classic',
        'draw_animation': 'roulette',
        'draw_animation_seconds': 4,
        'show_chances_overlay': False,
    })

    # ---- Log de atividades ----
    activity_log: deque = field(default_factory=lambda: deque(maxlen=300))

    # ---- Lock global ----
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)




# Instância global (uma única pra todo o processo)
STATE = AppState()


def participant_weight(platform: str, is_sub: bool, is_vip: bool, is_mod: bool = False) -> float:
    extras=STATE.multipliers.get(platform,{})
    return max([1.0]+[1.0+extras.get(role,0.0) for role,active in
        [('sub',is_sub),('vip',is_vip),('mod',is_mod)] if active])


def format_weight(value: float) -> str:
    return format(value,'.12g').replace('.',',')


# ==============================================================================
# 🔌 HELPERS
# ==============================================================================
def add_participant(
    platform: str,
    username: str,
    user_id: str = '',
    is_sub: bool = False,
    is_vip: bool = False,
    is_mod: bool = False,
    is_owner: bool = False,
    weight: float = 1.0,
) -> bool:
    """Adiciona participante se não existir. Retorna True se novo, False se duplicado.

    Chave de unicidade: (platform, username.lower()).
    """
    key = f'{platform}:{username.strip().lower()}'
    if key in STATE.participants:
        # já existe: incrementa contagem de mensagens (anti-bot futuro)
        STATE.participants[key].message_count += 1
        return False
    participant = Participant(
        platform=platform,
        username=username.strip(),
        user_id=user_id,
        is_sub=is_sub,
        is_vip=is_vip,
        is_mod=is_mod,
        is_owner=is_owner,
        weight=weight,
    )
    from . import antibot
    antibot.mark_on_entry(participant)
    STATE.participants[key] = participant
    return True


def clear_participants() -> int:
    """Remove todos os participantes. Retorna quantos foram removidos."""
    n = len(STATE.participants)
    STATE.participants.clear()
    return n


# ==============================================================================
# 📝 LOG
# ==============================================================================
def log(message: str, level: str = 'info') -> None:
    """Adiciona uma entrada ao log de atividades com timestamp."""
    STATE.activity_log.append({
        'time': time.time(),
        'level': level,
        'message': message,
    })

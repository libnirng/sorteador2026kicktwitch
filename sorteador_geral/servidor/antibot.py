"""Anti-bot / Captcha: gera challenges, valida respostas, gerencia estado do vencedor.

Tipos de challenge:
- math:  pergunta simples (ex: 2 + 3 = ?)
- word:  pede pra digitar uma palavra aleatória de uma lista
- code:  código de 4 caracteres (sem I/O/0/1)

State (no STATE):
- antibot_challenge: {
    'type': 'math'|'word'|'code',
    'question': 'Quanto é 2 + 3?',
    'expected': '5',
    'attempts': 0,
    'max_attempts': 3, # 0 para ilimitadas
    'issued_at': ts,
    'deadline': ts,
    'platform': 'twitch' | 'kick',
  }
"""
from __future__ import annotations

import logging
import random
import time
from typing import Any

from .state import STATE

logger = logging.getLogger(__name__)


# Palavras pro captcha tipo "word" (curtas, sem acentos pra evitar problemas de digitação)
WORD_POOL = [
    'foca', 'gato', 'cachorro', 'pato', 'macaco', 'leao', 'tigre', 'urso',
    'banana', 'morango', 'abacaxi', 'laranja', 'manga', 'mamao',
    'verde', 'azul', 'amarelo', 'rosa', 'branco', 'preto',
    'sorteio', 'vencedor', 'premio', 'trofeu', 'brilho', 'estrela',
    'computador', 'teclado', 'mouse', 'monitor', 'janela',
    'futebol', 'basquete', 'volei', 'tenis', 'natacao',
]


def _normalize(text: str) -> str:
    """Lowercase, sem espaços nas pontas, sem acentos. Pra comparar respostas."""
    import unicodedata
    text = text.strip().lower()
    # remove acentos: 'á' -> 'a'
    text = ''.join(
        c for c in unicodedata.normalize('NFD', text)
        if unicodedata.category(c) != 'Mn'
    )
    return text


def _make_code() -> tuple[str, str]:
    """Gera código de 4 chars (sem I/O/0/1)."""
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    code = ''.join(random.choices(alphabet, k=4))
    question = f'Digite o código: {code}'
    # A "resposta esperada" é o próprio código, mas o usuário digita
    return question, code


def _make_math() -> tuple[str, str]:
    """Gera conta simples (soma ou subtração com resultado >= 0)."""
    op = random.choice(['+', '-'])
    if op == '+':
        a = random.randint(1, 20)
        b = random.randint(1, 20)
        result = a + b
        question = f'Quanto é {a} + {b}?'
    else:
        a = random.randint(5, 30)
        b = random.randint(0, a)
        result = a - b
        question = f'Quanto é {a} - {b}?'
    return question, str(result)


def _make_word() -> tuple[str, str]:
    """Escolhe uma palavra da pool."""
    word = random.choice(WORD_POOL)
    question = f'Digite a palavra: {word}'
    return question, word


_GENERATORS = {
    'math': _make_math,
    'word': _make_word,
    'code': _make_code,
}


def _pick_type() -> str:
    """Escolhe um tipo de captcha ativo, aleatoriamente."""
    active = [t for t, on in STATE.antibot_types.items() if on]
    if not active:
        # se nada ativo, usa math
        return 'math'
    return random.choice(active)


def mark_on_entry(participant: Any) -> None:
    """Uma decisão por inscrição única; repetições não passam por esta função."""
    participant.captcha_decided_at = time.time()
    participant.captcha_chance_at_entry = STATE.antibot_random_chance
    participant.captcha_marked = False
    if not STATE.antibot_enabled:
        participant.captcha_status = 'disabled'
    elif STATE.captcha_waive_subs_vips and (participant.is_sub or participant.is_vip):
        participant.captcha_status = 'exempt'
    else:
        participant.captcha_marked = random.random() < STATE.antibot_random_chance / 100.0
        participant.captcha_status = 'marked' if participant.captcha_marked else 'not_selected'


def should_apply_to(participant: Any) -> bool:
    """Consulta a decisão da entrada. Nunca faz um novo sorteio de marcação."""
    return STATE.antibot_enabled and bool(getattr(participant, 'captcha_marked', False))


def set_participant_status(value: str) -> None:
    winner = STATE.current_winner
    if winner:
        participant = STATE.participants.get(f'{winner.platform}:{winner.username.strip().lower()}')
        if participant and participant.captcha_marked:
            participant.captcha_status = value


def marked_participants() -> list[dict]:
    return [{
        'username': p.username, 'platform': p.platform,
        'chance_at_entry': p.captcha_chance_at_entry,
        'decided_at': p.captcha_decided_at, 'status': p.captcha_status,
        'is_sub': p.is_sub, 'is_vip': p.is_vip,
    } for p in STATE.participants.values() if p.captcha_marked]


def issue(platform: str = 'twitch', *, timed: bool = True) -> dict:
    """Gera e armazena um novo challenge. Retorna o dict armazenado."""
    ctype = _pick_type()
    question, expected = _GENERATORS[ctype]()
    now = time.time()
    challenge = {
        'type': ctype,
        'question': question,
        'expected': expected,
        'attempts': 0,
        'max_attempts': STATE.antibot_max_attempts,
        'issued_at': now,
        # O relógio de presença já parou quando a pessoa respondeu no chat.
        # O desafio posterior não tem outro cronômetro automático.
        'deadline': now + STATE.winner_timer_seconds if timed else 0.0,
        'platform': platform,
    }
    challenge['username'] = STATE.current_winner.username if STATE.current_winner else ''
    STATE.antibot_challenge = challenge
    set_participant_status('challenged')
    logger.info('🛡️ Captcha emitido: %s', ctype)
    return challenge


def check(user_response: str) -> tuple[bool, str]:
    """Verifica a resposta do vencedor. Retorna (ok, status).

    status: 'ok' | 'wrong' | 'exhausted' | 'expired' | 'no_challenge'
    Incrementa `attempts` e limpa challenge somente se ok ou expirado.
    """
    c = STATE.antibot_challenge
    if c is None:
        return False, 'no_challenge'
    if c['deadline'] and time.time() > c['deadline']:
        set_participant_status('expired')
        STATE.antibot_challenge = None
        return False, 'expired'

    if _normalize(user_response) == _normalize(c['expected']):
        set_participant_status('passed')
        STATE.antibot_challenge = None
        return True, 'ok'

    c['attempts'] += 1
    if c['max_attempts'] and c['attempts'] >= c['max_attempts']:
        return False, 'exhausted'
    return False, 'wrong'


def cancel() -> None:
    """Cancela challenge em andamento (vencedor respondeu, foi pulado, etc)."""
    STATE.antibot_challenge = None


def status() -> dict | None:
    """Retorna o challenge atual (sem o expected, pra UI pública)."""
    c = STATE.antibot_challenge
    if c is None:
        return None
    return {
        'username': c.get('username', ''),
        'type': c['type'],
        'question': c['question'],
        'attempts': c['attempts'],
        'max_attempts': c['max_attempts'],
        'deadline': c['deadline'],
        'platform': c['platform'],
        'remaining': max(0, c['deadline'] - time.time()) if c['deadline'] else None,
    }


def status_full() -> dict | None:
    """Retorna o challenge com a resposta esperada (SÓ pro admin)."""
    c = STATE.antibot_challenge
    if c is None:
        return None
    return {
        **status(),
        'expected': c['expected'],
    }

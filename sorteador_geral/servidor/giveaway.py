"""Lógica completa do sorteio: iniciar, pausar, sortear vencedor, timer, re-sorteio.

Responsabilidades:
- Transitar entre estados: idle → open → paused → drawing → won → closed
- Sortear com peso (sub/vip/mod)
- Manter timer do vencedor atual (re-sorteia se não responder)
- Persistir sorteio e vencedor no banco
- Notificar via broadcast (chamado pelo app.py)

API:
- start(keyword) -> None    : limpa participantes, abre sorteio
- pause() / resume()        : pausar/retomar entradas
- stop()                    : fecha (mantém lista e vencedor atual)
- reset()                   : fecha e limpa tudo
- draw() -> Winner          : sorteia com peso
- answer(username) -> bool  : marca vencedor atual como respondeu
- skip()                    : pula vencedor atual sem resposta (re-sorteia)

Estado é gerenciado em STATE. Não toca em WebSocket direto.
Quem precisa notificar UI deve escutar broadcast via _notify_state.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

from . import db
from . import antibot
from .state import STATE, log, clear_participants

logger = logging.getLogger(__name__)

DRAW_ANIMATIONS = ('roulette', 'slots', 'countdown', 'cards', 'dice',
                   'radar', 'chest', 'particles', 'portal', 'spotlights')


# ============================================================================
# 📦 HELPERS
# ============================================================================
def _serialize_winner(w) -> dict:
    """Converte Winner (dataclass) em dict pra JSON."""
    return {
        'username': w.username,
        'platform': w.platform,
        'user_id': w.user_id,
        'weight': w.weight,
        'chance_pct': w.chance_pct,
        'award': w.award,
        'drawn_at': w.drawn_at,
        'answered': w.answered,
        'presence_confirmed': w.presence_confirmed,
        'captcha_required': w.captcha_required,
        'captcha_failed': w.captcha_failed,
        'delivered': w.delivered,
        'is_sub': getattr(w, 'is_sub', False),
        'is_vip': getattr(w, 'is_vip', False),
        'is_mod': getattr(w, 'is_mod', False),
        'avatar_url': getattr(w, 'avatar_url', ''),
    }


def _compute_chance_pct(weight: float, total_weight: float) -> float:
    """Calcula chance percentual: (peso / soma) * 100."""
    if total_weight <= 0:
        return 0.0
    return (weight / total_weight) * 100.0


# ============================================================================
# 🎰 LÓGICA DE SORTEIO
# ============================================================================
class GiveawayEngine:
    """Motor do sorteio. Singleton."""

    def __init__(self):
        self._timer_task: asyncio.Task | None = None
        self._reveal_task: asyncio.Task | None = None
        self._last_draw_animation: str = ''
        self._current_sorteio_id: int | None = None
        # Hook opcional pra notificar UI (app.py define _notify_state aqui)
        self.on_change: Any = None
        # ChatManager (opcional). Se setado, podemos enviar msgs no chat quando config pedir.
        self.chat: Any = None
        self._excluded: set[tuple[str, str]] = set()

    # =================== CONTROLE DE ESTADO ===================
    async def start(self, keyword: str = '') -> dict:
        """Inicia um sorteio novo. Limpa participantes e vencedor anterior."""
        keyword = (keyword or STATE.keyword or '').strip()
        if not keyword:
            raise ValueError('Palavra-chave é obrigatória.')
        if keyword.casefold() in (STATE.skip_chat_command.casefold(), STATE.nick_lookup_command.casefold(), STATE.rank_lookup_command.casefold()):
            raise ValueError('A palavra-chave não pode ser igual a um comando reservado do chat.')

        # Cancela timer pendente
        self._cancel_timer()
        self._cancel_reveal()
        STATE.draw_reveal_until = 0.0
        STATE.draw_animation_active = ''

        # Limpa participantes anteriores
        clear_participants()
        self._excluded.clear()
        STATE.winners.clear()
        STATE.winner_chat_messages.clear()
        STATE.current_winner = None
        STATE.winner_claim_pending = None
        STATE.winner_claim_recent = None
        STATE.winner_claim_feedback = None
        STATE.winner_claim_feedback_until = 0.0
        STATE.captcha_feedback = None
        STATE.winner_deadline = 0.0
        STATE.antibot_challenge = None
        STATE.skip_chat_uses = 0

        # Cria sorteio no banco
        self._current_sorteio_id = await db.sorteio_create(keyword)

        # Atualiza state
        STATE.is_running = True
        STATE.is_paused = False
        STATE.keyword = keyword
        await db.config_set('keyword', keyword)
        STATE.entry_open_twitch = STATE.accept_entries_twitch
        STATE.entry_open_kick = STATE.accept_entries_kick
        STATE.status_message = f'🟢 Sorteio aberto — palavra: {keyword}'
        log(f'🟢 Sorteio iniciado: keyword={keyword!r}')

        await db.audit_add('admin', 'start_giveaway', {'keyword': keyword})
        if self.on_change:
            await self.on_change()
        announcements = {}
        if self.chat:
            announcements = await self.chat.announce('giveaway_open')
        return {'ok': True, 'keyword': keyword, 'sorteio_id': self._current_sorteio_id,
                'announcements': announcements}

    async def pause(self) -> dict:
        if not STATE.is_running:
            raise ValueError('Sorteio não está aberto.')
        if STATE.is_paused:
            return {'ok': True, 'already_paused': True}
        STATE.is_paused = True
        STATE.status_message = '⏸️ Sorteio pausado'
        log('⏸️ Sorteio pausado')
        await db.audit_add('admin', 'pause_giveaway')
        if self.chat:
            await self.chat.announce('giveaway_paused')

        if self.on_change:
            await self.on_change()
        return {'ok': True}

    async def resume(self) -> dict:
        if not STATE.is_running:
            raise ValueError('Sorteio não está aberto.')
        if not STATE.is_paused:
            return {'ok': True, 'already_running': True}
        STATE.is_paused = False
        STATE.status_message = f'▶️ Inscrições retomadas — palavra: {STATE.keyword}'
        log('▶️ Sorteio retomado')
        await db.audit_add('admin', 'resume_giveaway')
        if self.chat:
            await self.chat.announce('giveaway_resumed')

        if self.on_change:
            await self.on_change()
        return {'ok': True}

    async def stop(self) -> dict:
        """Fecha o sorteio (mantém lista e vencedor atual)."""
        if not STATE.is_running:
            raise ValueError('Sorteio não está aberto.')
        self._cancel_timer()
        self._cancel_reveal()
        STATE.draw_reveal_until = 0.0
        STATE.draw_animation_active = ''
        STATE.winner_deadline = 0.0
        antibot.cancel()
        STATE.is_running = False
        STATE.winner_claim_pending = None
        STATE.winner_claim_recent = None
        STATE.winner_claim_feedback = None
        STATE.winner_claim_feedback_until = 0.0
        STATE.is_paused = False
        STATE.entry_open_twitch = False
        STATE.entry_open_kick = False
        STATE.status_message = '🔒 Sorteio encerrado'
        log('🔒 Sorteio encerrado')
        if self.on_change:
            await self.on_change()

        if self._current_sorteio_id is not None:
            await db.sorteio_update(
                self._current_sorteio_id,
                ended_at=time.time(),
                status='closed',
                total_participants=len(STATE.participants),
            )
        await db.audit_add('admin', 'stop_giveaway', {
            'total_participants': len(STATE.participants),
        })
        announcements = await self.chat.announce('giveaway_closed') if self.chat else {}
        return {'ok': True, 'total': len(STATE.participants), 'announcements': announcements}

    async def reset(self) -> dict:
        """Fecha e limpa tudo (participantes, vencedor, status)."""
        self._cancel_timer()
        self._cancel_reveal()
        STATE.draw_reveal_until = 0.0
        STATE.draw_animation_active = ''
        antibot.cancel()
        STATE.captcha_feedback = None
        clear_participants()
        self._excluded.clear()
        STATE.winners.clear()
        STATE.winner_chat_messages.clear()
        STATE.current_winner = None
        STATE.winner_claim_pending = None
        STATE.winner_claim_recent = None
        STATE.winner_claim_feedback = None
        STATE.winner_claim_feedback_until = 0.0
        STATE.winner_deadline = 0.0
        STATE.is_running = False
        STATE.is_paused = False
        STATE.antibot_challenge = None
        STATE.skip_chat_uses = 0
        STATE.status_message = '🧹 Sorteio resetado'
        log('🧹 Sorteio resetado')
        await db.audit_add('admin', 'reset_giveaway')
        if self.on_change:
            await self.on_change()
        return {'ok': True}

    # =================== SORTEIO ===================
    def _build_pool(self) -> tuple[list, float]:
        """Monta pool de participantes elegíveis e soma de pesos.

        Critérios (do STATE):
        - allow_viewers: viewers comuns podem entrar
        - allow_subs: subs podem entrar
        - allow_vips: vips podem entrar
        - allow_mods: mods podem entrar
        - block_repeat_winner: se alguém já ganhou neste sorteio, não entra de novo

        Os controles de novas inscrições não removem participantes já inscritos.
        """
        eligible = []
        already_won_usernames = {
            w.username.lower() for w in STATE.winners
        } if STATE.block_repeat_winner else set()

        drawn_names={(w.platform,w.username.casefold()) for w in STATE.winners}
        drawn_ids={(w.platform,str(w.user_id)) for w in STATE.winners if w.user_id}
        for p in STATE.participants.values():
            if not p.active:
                continue  # desativado manualmente na aba Participantes
            if p.is_winner or (p.platform,p.username.casefold()) in drawn_names or (p.user_id and (p.platform,str(p.user_id)) in drawn_ids):
                continue  # quem já foi sorteado fica marcado até iniciar outra coleta
            if (p.platform, p.username.casefold()) in self._excluded:
                continue
            # Bloqueio por tipo
            if not STATE.allow_viewers and not (p.is_sub or p.is_vip or p.is_mod):
                continue
            if not STATE.allow_subs and p.is_sub:
                continue
            if not STATE.allow_vips and p.is_vip:
                continue
            if p.is_mod and not STATE.platform_mods.get(p.platform, STATE.allow_mods):
                continue

            # Bloqueio por já ter ganhado
            if p.username.lower() in already_won_usernames:
                continue

            eligible.append(p)

        total = sum(p.weight for p in eligible)
        return eligible, total

    def compute_chances(self) -> list[dict]:
        """Calcula % de cada participante pra exibir na aba Chances."""
        eligible, total = self._build_pool()
        out = []
        for p in eligible:
            out.append({
                'platform': p.platform,
                'username': p.username,
                'user_id': p.user_id,
                'is_sub': p.is_sub,
                'is_vip': p.is_vip,
                'is_mod': p.is_mod,
                'weight': p.weight,
                'chance_pct': _compute_chance_pct(p.weight, total),
                'first_seen': p.first_seen,
            })
        out.sort(key=lambda x: -x['chance_pct'])
        return out

    async def draw(self, award: str = '') -> dict:
        """Sorteia um vencedor com peso. Dispara timer de resposta."""
        if not STATE.is_running:
            raise ValueError('Sorteio não está aberto.')
        if STATE.current_winner is not None:
            raise ValueError('Já existe um vencedor ativo — responda ou pule antes de sortear de novo.')
        from . import giveaway_prizes
        selected=giveaway_prizes.selected() if not award else None

        eligible, total = self._build_pool()
        if not eligible or total <= 0:
            raise ValueError('Nenhum participante elegível.')

        # Sorteio com peso (algoritmo da roleta ponderada)
        r = random.random() * total
        acc = 0.0
        winner_p = None
        for p in eligible:
            acc += p.weight
            if r <= acc:
                winner_p = p
                break
        # fallback (arredondamento)
        if winner_p is None:
            winner_p = eligible[-1]

        # Escolhe no servidor agora, mas aguarda o suspense antes de revelar.
        from .state import Winner
        winner = Winner(
            platform=winner_p.platform,
            username=winner_p.username,
            user_id=winner_p.user_id,
            weight=winner_p.weight,
            chance_pct=_compute_chance_pct(winner_p.weight, total),
            award=award or (selected['name'] if selected else '🎁 Prêmio'),
            prize_id=selected['id'] if selected else '',
            drawn_at=time.time(),
            is_sub=bool(getattr(winner_p, 'is_sub', False)),
            is_vip=bool(getattr(winner_p, 'is_vip', False)),
            is_mod=bool(getattr(winner_p, 'is_mod', False)),
            avatar_url=winner_p.avatar_url,
        )
        STATE.winner_chat_messages.clear()
        STATE.winner_claim_pending = None
        STATE.winner_claim_recent = None
        STATE.winner_claim_feedback = None
        STATE.winner_claim_feedback_until = 0.0
        winner_p.is_winner = True
        STATE.winners.append(winner)
        STATE.current_winner = winner
        STATE.captcha_feedback = None
        self._cancel_reveal()
        animation=STATE.appearance.get('draw_animation', 'roulette')
        if animation == 'random':
            # Uma decisão única no servidor mantém todas as telas OBS sincronizadas
            # e evita repetir a mesma animação em dois vencedores consecutivos.
            choices=[style for style in DRAW_ANIMATIONS if style != self._last_draw_animation]
            animation=random.choice(choices)
        STATE.draw_animation_active=animation
        if animation != 'none':
            self._last_draw_animation=animation
        suspense=float(STATE.appearance.get('draw_animation_seconds', 4)) if animation != 'none' else 0.0
        STATE.draw_reveal_until=0.0
        STATE.winner_deadline=0.0
        STATE.status_message = (
            f'🏆 Vencedor: {winner.username} '
            f'({winner_p.weight:.1f}x, {winner.chance_pct:.2f}%)'
        )
        log(
            f'🏆 Vencedor sorteado: {winner.username} ({winner.platform}) '
            f'peso={winner.weight} chance={winner.chance_pct:.2f}%'
        )

        # Persiste
        winner_db_id = await db.winner_insert({
            'platform': winner.platform,
            'username': winner.username,
            'user_id': winner.user_id,
            'weight': winner.weight,
            'chance_pct': winner.chance_pct,
            'award': winner.award,
            'drawn_at': winner.drawn_at,
            'is_sub': getattr(winner, 'is_sub', False),
            'is_vip': getattr(winner, 'is_vip', False),
            'is_mod': getattr(winner, 'is_mod', False),
        }, sorteio_id=self._current_sorteio_id)
        winner.db_id = winner_db_id  # type: ignore[attr-defined]

        await db.audit_add('admin', 'draw_winner', {
            'username': winner.username, 'platform': winner.platform,
            'weight': winner.weight, 'chance_pct': winner.chance_pct,
        })


        # Primeiro aguarda QUALQUER mensagem do vencedor e cronometra apenas
        # sua presença. Se foi marcado, o captcha só é gerado DEPOIS disso.
        winner.captcha_required = antibot.should_apply_to(winner_p)
        antibot.cancel()
        winner.challenge = ''

        # Começar o suspense APÓS as gravações no banco: atrasos na escrita
        # não podem consumir os segundos de animação sem o OBS receber estado.
        STATE.draw_reveal_until=time.time()+suspense if suspense > 0 else 0.0
        STATE.winner_deadline=0.0 if suspense > 0 else time.time()+STATE.winner_timer_seconds
        if suspense > 0:
            self._reveal_task=asyncio.create_task(self._finish_reveal(winner))
        else:
            self.restart_timer()
        if self.on_change:
            await self.on_change()
        if suspense == 0 and self.chat and STATE.current_winner is winner:
            await self.chat.announce('winner_announced', nome=winner.username, plataforma=winner.platform,
                                     tempo=max(0, round(STATE.winner_deadline - time.time())))
        return _serialize_winner(winner)

    async def _finish_reveal(self, winner) -> None:
        """Só após o suspense inicia o prazo completo e anuncia no chat."""
        try:
            await asyncio.sleep(max(0, STATE.draw_reveal_until - time.time()))
            if STATE.current_winner is not winner or not STATE.is_running:
                return
            STATE.draw_reveal_until=0.0
            STATE.winner_deadline=time.time() + STATE.winner_timer_seconds
            self.restart_timer()
            if self.on_change:
                await self.on_change()
            if self.chat and STATE.current_winner is winner:
                await self.chat.announce('winner_announced', nome=winner.username,
                    plataforma=winner.platform, tempo=max(0, round(STATE.winner_deadline - time.time())))
        except asyncio.CancelledError:
            pass
        finally:
            if self._reveal_task is asyncio.current_task():
                self._reveal_task=None

    def _cancel_reveal(self) -> None:
        if self._reveal_task and self._reveal_task is not asyncio.current_task() and not self._reveal_task.done():
            self._reveal_task.cancel()
        self._reveal_task=None

    async def confirm_presence(self) -> dict:
        """Primeira mensagem do vencedor: encerra o prazo e só então cria captcha."""
        w = STATE.current_winner
        if w is None or w.presence_confirmed:
            raise ValueError('Não há presença pendente de confirmação.')
        if STATE.draw_reveal_until > time.time():
            raise ValueError('A revelação do vencedor ainda não terminou.')
        # Atualizar o estado ANTES de qualquer await impede mensagens duplicadas
        # de reiniciarem o relógio ou emitirem novos códigos.
        w.presence_confirmed = True
        w.responded_at = time.time()
        w.answered = True  # para !rank: respondeu, mesmo que erre o captcha
        w.outcome = 'captcha_pending' if w.captcha_required else 'answered'
        self._cancel_timer()
        STATE.winner_deadline = 0.0
        if w.captcha_required:
            challenge = antibot.issue(platform=w.platform, timed=False)
            w.challenge = challenge['question']
            w.captcha_text = challenge['question']
            STATE.status_message = f'🛡️ {w.username} respondeu. Cronômetro encerrado; aguardando captcha.'
        else:
            STATE.status_message = f'✅ {w.username} respondeu.'
        db_id = getattr(w, 'db_id', None)
        if db_id:
            await db.winner_update(db_id, answered=True, responded_at=w.responded_at,
                captcha_text=w.captcha_text, outcome=w.outcome)
        if w.captcha_required:
            await db.audit_add('chat', 'captcha_issued', {
                'username': w.username, 'platform': w.platform,
                'type': STATE.antibot_challenge['type'],
            })
        if self.on_change:
            await self.on_change()
        return {'ok': True, 'captcha': antibot.status()}

    async def submit_captcha(self, response: str) -> dict:
        """Permite retentativas sem revelar a solução antes do limite configurado."""
        w = STATE.current_winner
        challenge = STATE.antibot_challenge
        if w is None or not w.presence_confirmed or challenge is None:
            raise ValueError('Não há captcha em andamento.')
        expected = str(challenge['expected'])
        ok, status = antibot.check(response)
        if status == 'expired':
            return {'ok': False, 'status': 'expired'}
        attempts=int(challenge.get('attempts',0))
        maximum=int(challenge.get('max_attempts',STATE.antibot_max_attempts) or 0)
        remaining=max(0,maximum-attempts) if maximum else None
        exhausted=status=='exhausted'
        STATE.captcha_feedback = {
            'username': w.username, 'platform': w.platform,
            'status': 'correct' if ok else 'wrong', 'at': time.time(),
            'attempts':attempts, 'max_attempts':maximum,
            'remaining':remaining, 'exhausted':exhausted,
            **({'expected': expected} if exhausted else {}),
        }
        if ok:
            w.captcha_passed = True
            await self.answer()
            if self.chat:
                # As duas mensagens são enviadas EM ORDEM; a orientação não
                # pode ultrapassar o aviso de resposta correta no chat.
                messages = [('captcha_success', {'platform':w.platform,'nome':w.username})]
                if STATE.nick_lookup_enabled:
                    messages.append(('winner_claim_instructions',
                        {'platform':w.platform,'nome':w.username,'premio':w.award}))
                self.chat._schedule_ordered_announcements(messages)
            return {'ok': True, 'status': 'ok'}
        if not exhausted:
            STATE.status_message=(f'❌ {w.username}: tentativa {attempts}/'
                f'{maximum if maximum else "∞"} incorreta. Aguardando nova resposta.')
            if self.on_change:
                await self.on_change()
            return {'ok':False,'status':'wrong','attempts':attempts,
                    'max_attempts':maximum,'remaining':remaining,'exhausted':False}
        # Esgotadas as tentativas: revela a solução, encerra o desafio e
        # conserva o vencedor para a decisão manual do organizador.
        antibot.set_participant_status('failed')
        antibot.cancel()
        w.captcha_failed = True
        w.outcome = 'captcha_failed'
        STATE.status_message = f'❌ {w.username} errou o captcha. Aguarde decisão do organizador.'
        db_id = getattr(w, 'db_id', None)
        if db_id:
            await db.winner_update(db_id, answered=True, responded_at=w.responded_at,
                captcha_text=w.captcha_text, captcha_passed=False,
                delivered=False, outcome=w.outcome)
        await db.audit_add('chat', 'captcha_failed', {'username':w.username,
            'platform':w.platform,'attempts':attempts,'max_attempts':maximum})
        if self.on_change:
            await self.on_change()
        return {'ok': False, 'status': 'wrong', 'expected': expected,
                'attempts':attempts,'max_attempts':maximum,'remaining':0,'exhausted':True}

    async def answer(self) -> dict:
        """Marca o vencedor atual como tendo respondido."""
        if STATE.current_winner is None:
            raise ValueError('Não há vencedor ativo.')
        w = STATE.current_winner
        self._cancel_reveal()
        STATE.draw_reveal_until = 0.0
        # Fecha a confirmação antes de qualquer await: timeout e mensagens repetidas
        # não podem confirmar ou substituir outro vencedor ao mesmo tempo.
        if STATE.antibot_challenge:
            antibot.set_participant_status('confirmed')
        STATE.current_winner = None
        STATE.winner_claim_pending = w if STATE.nick_lookup_enabled else None
        STATE.winner_claim_recent = None
        STATE.winner_claim_feedback = None
        STATE.winner_claim_feedback_until = 0.0
        w.answered = True
        w.outcome = 'answered'
        w.responded_at = w.responded_at or time.time()
        w.delivered = True
        self._cancel_timer()
        STATE.winner_deadline = 0.0
        antibot.cancel()
        STATE.status_message = (f'✅ {w.username} respondeu! Aguardando '
            f'{STATE.nick_lookup_command} NomeDoPersonagem (sem prazo).'
            if STATE.winner_claim_pending else f'✅ {w.username} respondeu! Pronto para o próximo sorteio.')
        log(f'✅ Vencedor {w.username} respondeu')
        db_id = getattr(w, 'db_id', None)
        if db_id:
            await db.winner_update(db_id, answered=True, responded_at=w.responded_at,
                delivered=True, captcha_text=w.captcha_text,
                captcha_passed=w.captcha_passed, outcome='answered')
        await db.audit_add('admin', 'winner_answered', {'username': w.username})
        if self.on_change:
            await self.on_change()
        if self.chat and STATE.nick_lookup_enabled and not (w.captcha_required and w.captcha_passed):
            # A resposta do vencedor comum confirma imediatamente; para o
            # marcado que acertou o CAPTCHA, a orientação é enviada somente
            # DEPOIS do anúncio de resposta correta, em submit_captcha().
            self.chat._schedule_announcement('winner_claim_instructions',
                platform=w.platform, nome=w.username, premio=w.award)
        return {'ok': True, 'winner': _serialize_winner(w)}

    async def skip(self, award: str | None = None, *, reason: str = 'manual') -> dict:
        """Pula o vencedor atual (sem resposta) e re-sorteia."""
        if STATE.current_winner is None:
            raise ValueError('Não há vencedor ativo.')
        w = STATE.current_winner
        self._cancel_reveal()
        STATE.draw_reveal_until = 0.0
        w.outcome = 'declined' if reason == 'chat_voluntary' else 'skipped'
        self._excluded.add((w.platform, w.username.casefold()))
        self._cancel_timer()
        if STATE.antibot_challenge:
            antibot.set_participant_status('skipped')
        STATE.current_winner = None
        antibot.cancel()
        STATE.winner_deadline = 0.0
        log(f'⏭️ Vencedor {w.username} pulado, re-sorteando...')
        await db.audit_add('admin', 'skip_winner', {
            'username': w.username, 'platform': w.platform, 'reason': reason,
        })
        db_id = getattr(w, 'db_id', None)
        if db_id:
            await db.winner_update(db_id, answered=w.answered, responded_at=w.responded_at or None,
                delivered=False, outcome=w.outcome)
        if STATE.current_winner is not None:
            return None
        STATE.status_message = '⏭️ Vencedor pulado, re-sorteando...'
        if self.on_change:
            await self.on_change()
        # Re-sorteia (pode falhar se pool esvaziou; nesse caso só limpa)
        try:
            return await self.draw(award=self._retry_award(w) if award is None else award)
        except ValueError as e:
            log(f'⚠️ Re-sorteio falhou: {e}')
            STATE.status_message = f'⚠️ Re-sorteio falhou: {e}'
            if self.on_change:
                await self.on_change()
            return None

    # =================== TIMER ===================
    def _retry_award(self,winner):
        from . import giveaway_prizes
        selected=giveaway_prizes.selected()
        if selected:return ''  # draw resolve o catálogo e registra a origem novamente
        if winner.prize_id:
            raise ValueError('O prêmio anterior não está mais disponível. Selecione outro prêmio para continuar.')
        return winner.award

    def restart_timer(self) -> None:
        self._cancel_timer()
        if STATE.current_winner:
            self._timer_task = asyncio.create_task(self._winner_timeout(STATE.current_winner))

    def _cancel_timer(self) -> None:
        if self._timer_task and self._timer_task is not asyncio.current_task() and not self._timer_task.done():
            self._timer_task.cancel()
        self._timer_task = None

    async def _winner_timeout(self, winner) -> None:
        """Roda em background; quando o tempo expira, re-sorteia."""
        try:
            await asyncio.sleep(max(0, STATE.winner_deadline - time.time()))
            if STATE.current_winner is not winner:
                return  # já respondeu ou foi pulado
            self._excluded.add((winner.platform, winner.username.casefold()))
            winner.outcome = 'timeout'
            if winner.captcha_required or STATE.antibot_challenge:
                antibot.set_participant_status('expired')
                STATE.captcha_feedback={'username':winner.username,'platform':winner.platform,'status':'expired','at':time.time()}
            antibot.cancel()
            STATE.current_winner = None
            STATE.draw_reveal_until = 0.0
            STATE.winner_deadline = 0.0
            log(f'⏰ Vencedor {winner.username} não respondeu a tempo.')
            STATE.status_message = f'⏰ Prazo de {winner.username} encerrado. ' + ('Sorteando próximo...' if STATE.auto_advance_timeout else 'Clique em Sortear próximo para continuar com a mesma lista.')
            await db.audit_add('admin', 'skip_winner', {
                'username': winner.username, 'platform': winner.platform, 'reason': 'timeout',
            })
            db_id = getattr(winner, 'db_id', None)
            if db_id:
                await db.winner_update(db_id, answered=False, delivered=False, outcome='timeout')
            if STATE.current_winner is not None:
                return
            if self.on_change:
                await self.on_change()
            if self.chat:
                await self.chat.announce('winner_no_response', platform=winner.platform, nome=winner.username,
                    proximo='Sorteando próximo vencedor...' if STATE.auto_advance_timeout else 'Aguardando o próximo sorteio manual.')
            if not STATE.auto_advance_timeout or not STATE.is_running or STATE.current_winner is not None:
                return
            try:
                await self.draw(award=self._retry_award(winner))
            except ValueError as e:
                log(f'⚠️ Re-sorteio falhou: {e}', 'warn')
                STATE.status_message = f'⚠️ Sem mais participantes elegíveis.'
                if self.on_change:
                    await self.on_change()
        except asyncio.CancelledError:
            pass
        finally:
            if self._timer_task is asyncio.current_task():
                self._timer_task = None


# Singleton
giveaway = GiveawayEngine()

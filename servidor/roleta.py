"""Roleta: itens, spin ponderado, histórico.

A roleta é um recurso opcional — o admin cadastra prêmios (com peso) e gira
um ponteiro virtual que escolhe um deles. O resultado aparece no overlay e
fica gravado em roleta_history + audit.

Normalização (modelo do zip antigo):
Os valores digitados são preservados no banco e na edição. Apenas o snapshot
do giro e a escolha ponderada usam valores normalizados. Se todos os
ativos forem 0, divide 100% igual entre eles.
"""
from __future__ import annotations

import asyncio
import random
import time
from typing import Any

from . import db
from .state import STATE, RoletaItem, log

on_change = None
_lifecycle_task = None

def _cancel_lifecycle():
    global _lifecycle_task
    if _lifecycle_task and _lifecycle_task is not asyncio.current_task():
        _lifecycle_task.cancel()
    _lifecycle_task = None

async def _complete_later(spin_id):
    await asyncio.sleep(STATE.roleta_duration_seconds + 3)
    if STATE.roleta_current_spin_id == spin_id and STATE.roleta_spinning:
        await mark_finished()
        if on_change:
            await on_change()

async def _after_result(spin_id):
    await asyncio.sleep(STATE.roleta_result_seconds)
    if STATE.roleta_current_spin_id != spin_id:
        return
    if STATE.roleta_remaining > 0:
        STATE.roleta_remaining -= 1
        result = await spin(STATE.roleta_last_nick)
        if result is None:
            await set_visible(False)
            log('🎰 Sequência encerrada: não há mais prêmios ativos.')
    elif STATE.roleta_auto_hide:
        await set_visible(False)
    if on_change:
        await on_change()


def _normalize_items(items: list[RoletaItem]) -> list[RoletaItem]:
    """Reescala os pesos dos itens ativos pra somar 100.
    Se todos ativos forem 0, divide 100% igual. Inativos ficam como estão.
    Retorna nova lista (não muta in-place)."""
    if not items:
        return items
    ativos = [i for i in items if i.active]
    if not ativos:
        return items
    total = sum(i.weight for i in ativos)
    if total <= 1e-6:
        valor = 100.0 / len(ativos)
        out = []
        for i in items:
            if i.active:
                out.append(RoletaItem(
                    id=i.id, name=i.name, weight=round(valor, 4),
                    active=i.active, icon=i.icon,
                ))
            else:
                out.append(i)
        return out
    fator = 100.0 / total
    out = []
    acumulado = 0.0
    for idx, i in enumerate(items):
        if not i.active:
            out.append(i)
            continue
        novo = round(i.weight * fator, 4)
        # corrige arredondamento no último item pra fechar exatamente 100
        if idx == len(items) - 1 or (idx - len([x for x in items[:idx] if not x.active])) == len(ativos) - 1:
            novo = round(100.0 - acumulado, 4)
        else:
            acumulado += novo
        out.append(RoletaItem(
            id=i.id, name=i.name, weight=novo,
            active=i.active, icon=i.icon,
        ))
    return out


def normalized_items() -> list[RoletaItem]:
    """Itens normalizados (chance fechando 100) pra exibir/girar."""
    return _normalize_items(list(STATE.roleta_items))


async def load_items_from_db() -> None:
    """Carrega os itens do DB pro state (chamado no startup)."""
    rows = await db.roleta_list()
    STATE.roleta_items = [
        RoletaItem(
            id=r['id'], name=r['name'], weight=r['weight'],
            active=r['active'], icon=r.get('icon', '🎁'),
        )
        for r in rows
    ]


async def add_or_update_item(item: dict) -> int:
    """Cria ou atualiza um item. Devolve o id."""
    item_id = await db.roleta_upsert(item)
    await load_items_from_db()
    action = 'roleta_item_updated' if item.get('id') else 'roleta_item_added'
    await db.audit_add('admin', action, {'name': item.get('name', ''),
                                          'weight': item.get('weight', 1.0)})
    return item_id


async def delete_item(item_id: int) -> None:
    await db.roleta_delete(item_id)
    await load_items_from_db()
    await db.audit_add('admin', 'roleta_item_deleted', {'id': item_id})


def _pick_weighted() -> tuple[RoletaItem, int] | None:
    """Escolhe um item ativo aleatório, ponderado. Devolve (index, item) na lista ORIGINAL.
    Usa pesos normalizados (soma 100)."""
    norm = normalized_items()
    active = [(i, it) for i, it in enumerate(norm) if it.active]
    if not active:
        return None
    weights = [it.weight for _, it in active]
    chosen = random.choices(active, weights=weights, k=1)[0]
    # mapear de volta pro índice em STATE.roleta_items (mesmo id, mas o array pode
    # estar na mesma ordem após normalização)
    return chosen  # (index, item normalizado)


async def spin(nick: str = '') -> dict | None:
    """Gira a roleta. Devolve {item, index, spin_id, nick} ou None se sem itens ativos."""
    global _lifecycle_task
    if STATE.roleta_spinning:
        raise ValueError('Aguarde o giro atual terminar.')
    _cancel_lifecycle()
    if not STATE.roleta_items:
        return None
    picked = _pick_weighted()
    if not picked:
        return None
    index, item = picked
    STATE.roleta_spinning = True
    STATE.roleta_current_spin_id = max(STATE.roleta_current_spin_id + 1, time.time_ns() // 1000000)
    STATE.roleta_last_ack = 0
    STATE.roleta_last_index = index
    STATE.roleta_last_prize = item.name
    STATE.roleta_last_winner = ''  # preenchido depois se houver vencedor
    STATE.roleta_last_nick = nick
    STATE.roleta_visible = True

    # Snapshot do giro: items, duração e voltas NO MOMENTO do spin.
    # O overlay lê isso para garantir consistência mesmo se a config mudar depois.
    STATE.roleta_active_spin = {
        'spin_id': STATE.roleta_current_spin_id,
        'index': index,
        'prize_id': item.id,
        'prize_name': item.name,
        'prize_icon': item.icon,
        'nick': nick,
        'attempt': STATE.roleta_total - STATE.roleta_remaining,
        'total_attempts': STATE.roleta_total,
        'duration_seconds': float(STATE.roleta_duration_seconds),
        'extra_spins': int(STATE.roleta_extra_spins),
        'equal_slices': STATE.roleta_equal_slices,
        'started_at': time.time(),
        # items como serão desenhados: cada um com seu ângulo (proporcional ao peso
        # normalizado) e índices. Inativos vão ao final como fatia "excluído".
        'items': [
            {
                'id': i.id, 'name': i.name, 'icon': i.icon,
                'active': i.active, 'weight': i.weight,
            }
            for i in normalized_items()
        ],
    }

    _lifecycle_task = asyncio.create_task(_complete_later(STATE.roleta_current_spin_id))

    # Registra imediatamente (winner="" — admin atribui depois)
    await db.roleta_history_add(
        winner='', prize=item.name, spin_index=index, nick=nick,
    )
    await db.audit_add('admin', 'roleta_spin', {
        'prize': item.name, 'index': index, 'item_id': item.id, 'nick': nick,
    })
    log(f'🎰 Roleta girou: {item.name} (peso normalizado={item.weight:.2f}%) nick={nick!r}')
    return {
        'item': {
            'id': item.id, 'name': item.name, 'icon': item.icon,
            'weight': item.weight,
        },
        'index': index,
        'spin_id': STATE.roleta_current_spin_id,
        'nick': nick,
    }


async def set_visible(visible: bool) -> None:
    STATE.roleta_visible = visible
    if not visible:
        _cancel_lifecycle()
        STATE.roleta_spinning = False
        STATE.roleta_remaining = 0
        STATE.roleta_active_spin = None


async def mark_finished(winner: str = '') -> None:
    global _lifecycle_task
    if not STATE.roleta_spinning:
        return
    _cancel_lifecycle()
    STATE.roleta_spinning = False
    if STATE.roleta_active_spin:
        STATE.roleta_active_spin['finished'] = True
    STATE.roleta_last_winner = winner or STATE.roleta_last_nick
    if not STATE.roleta_test_mode:
        from .chat_manager import get_chat_manager
        await get_chat_manager().announce('prize_won', nome=STATE.roleta_last_nick,
                                         premio=STATE.roleta_last_prize)
    _lifecycle_task = asyncio.create_task(_after_result(STATE.roleta_current_spin_id))
    log('🎰 Roleta concluída')

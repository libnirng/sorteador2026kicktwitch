"""Analytics: fairness report, export CSV/JSON.

Usado pelo admin pra auditar a integridade do sorteio:
- Fairness: distribuição real vs esperada por plataforma/tipo
- Audit: listar eventos de auditoria
- Export: gerar CSV de participantes / vencedores / audit
"""
from __future__ import annotations

import csv
import io
import json
import time
from collections import Counter, defaultdict
from typing import Any

from . import db
from .state import STATE


async def fairness_report() -> dict:
    """Relatório de fairness do sorteio atual + histórico.

    Métricas:
    - total de vencedores por plataforma
    - distribuição por tipo (sub/vip/mod/viewer) entre vencedores vs participantes
    - participação: % que entrou e nunca ganhou
    - desvio: % de sortudos (>1 vitória) vs azarados (0 vitórias, muitos participantes)
    """
    winners = await db.winners_list(limit=10000)  # todos

    # Mapa username → quantas vezes ganhou
    win_count: Counter[str] = Counter()
    wins_by_type: Counter[str] = Counter()
    wins_by_platform: Counter[str] = Counter()
    for w in winners:
        username = w['username']
        win_count[username] += 1
        is_sub = bool(w.get('is_sub'))
        is_vip = bool(w.get('is_vip'))
        is_mod = bool(w.get('is_mod'))
        if is_mod:
            t = 'mod'
        elif is_vip:
            t = 'vip'
        elif is_sub:
            t = 'sub'
        else:
            t = 'viewer'
        wins_by_type[t] += 1
        wins_by_platform[w['platform']] += 1

    # Estado atual
    current = list(STATE.participants.values())
    total_now = len(current)
    part_by_type: Counter[str] = Counter()
    for p in current:
        if p.is_mod:
            t = 'mod'
        elif p.is_vip:
            t = 'vip'
        elif p.is_sub:
            t = 'sub'
        else:
            t = 'viewer'
        part_by_type[t] += 1

    # Multi-vencedores: usernames que ganharam mais de 1 vez
    multi_winners = sum(1 for c in win_count.values() if c > 1)
    # Quem entrou e nunca ganhou (na pool atual)
    current_winners = set(win_count.keys())
    never_won = sum(1 for p in current if p.username.lower() not in
                    {w.lower() for w in current_winners})

    total_wins = len(winners)

    # Top sortudos e azarados
    top_winners = win_count.most_common(5)

    return {
        'total_winners': total_wins,
        'wins_by_platform': dict(wins_by_platform),
        'wins_by_type': dict(wins_by_type),
        'current_participants': total_now,
        'participants_by_type': dict(part_by_type),
        'multi_winners': multi_winners,  # pessoas que ganharam 2+ vezes
        'never_won': never_won,           # na pool atual, quantos nunca ganharam
        'top_winners': [
            {'username': u, 'wins': c} for u, c in top_winners
        ],
        'unique_winner_usernames': len(win_count),
        'unique_winner_pct': (
            round(100 * len(win_count) / total_wins, 1) if total_wins else 0
        ),
    }


async def audit_list(limit: int = 200, action_filter: str = '') -> list[dict]:
    """Lista eventos de auditoria (mais recentes primeiro)."""
    rows = await db.audit_list(limit=limit)
    if action_filter:
        rows = [r for r in rows if action_filter.lower() in r.get('action', '').lower()]
    # formata ts pra humano
    for r in rows:
        try:
            r['ts_human'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r['ts']))
        except Exception:
            r['ts_human'] = '-'
    return rows


def _to_csv(rows: list[dict], columns: list[str]) -> str:
    """Gera CSV a partir de uma lista de dicts."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction='ignore')
    writer.writeheader()
    for r in rows:
        row = {}
        for c in columns:
            v = r.get(c, '')
            if isinstance(v, bool):
                v = '1' if v else '0'
            row[c] = v
        writer.writerow(row)
    return buf.getvalue()


async def export_participants_csv() -> str:
    """Exporta participantes da sessão atual (in-memory)."""
    rows = []
    for p in STATE.participants.values():
        rows.append({
            'username': p.username,
            'platform': p.platform,
            'user_id': p.user_id,
            'is_sub': bool(p.is_sub),
            'is_vip': bool(p.is_vip),
            'is_mod': bool(p.is_mod),
            'is_owner': bool(p.is_owner),
            'weight': p.weight,
            'first_seen': p.first_seen,
        })
    return _to_csv(rows, [
        'username', 'platform', 'user_id', 'is_sub', 'is_vip', 'is_mod', 'is_owner',
        'weight', 'first_seen',
    ])


async def export_winners_csv() -> str:
    """Exporta histórico de vencedores (do banco)."""
    rows = await db.winners_list(limit=100000)
    # converte ts pra legível
    for r in rows:
        try:
            r['drawn_at_human'] = time.strftime(
                '%Y-%m-%d %H:%M:%S', time.localtime(r.get('drawn_at') or 0)
            )
        except Exception:
            r['drawn_at_human'] = '-'
    return _to_csv(rows, [
        'id', 'sorteio_id', 'platform', 'username', 'user_id',
        'is_sub', 'is_vip', 'is_mod',
        'weight', 'award', 'drawn_at_human', 'answered', 'delivered',
    ])


async def export_audit_csv() -> str:
    """Exporta audit log."""
    rows = await db.audit_list(limit=100000)
    for r in rows:
        try:
            r['ts_human'] = time.strftime(
                '%Y-%m-%d %H:%M:%S', time.localtime(r.get('ts') or 0)
            )
        except Exception:
            r['ts_human'] = '-'
        # serializa payload pra string
        r['payload'] = json.dumps(r.get('payload') or {}, ensure_ascii=False)
    return _to_csv(rows, ['ts_human', 'actor', 'action', 'payload'])

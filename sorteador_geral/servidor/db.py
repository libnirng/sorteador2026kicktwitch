"""Persistência em SQLite (async, via aiosqlite).

Guarda tudo que precisa sobreviver entre execuções:
- configurações (twitch, kick, mensagens, aparência)
- prêmios da roleta
- histórico de sorteios (vencedores, datas, prêmios)
- auditoria de alterações administrativas

Schema é criado/migrado automaticamente no startup. Backups automáticos
são feitos antes de cada escrita pesada (ver backup_now).
"""
from __future__ import annotations

import asyncio
from bisect import bisect_right
import json
import logging
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from .state import STATE, log

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / 'dados' / 'sorteador.db'
BACKUP_DIR = ROOT / 'dados' / 'backups'


SCHEMA = """
CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS roleta (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    active INTEGER NOT NULL DEFAULT 1,
    icon TEXT NOT NULL DEFAULT '🎁',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sorteios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at REAL NOT NULL,
    ended_at REAL,
    keyword TEXT,
    total_participants INTEGER DEFAULT 0,
    status TEXT  -- 'open','paused','closed','completed'
);

CREATE TABLE IF NOT EXISTS winners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sorteio_id INTEGER,
    platform TEXT NOT NULL,
    username TEXT NOT NULL,
    user_id TEXT,
    weight REAL NOT NULL,
    chance_pct REAL NOT NULL,
    award TEXT,
    drawn_at REAL NOT NULL,
    answered INTEGER NOT NULL DEFAULT 0,
    outcome TEXT NOT NULL DEFAULT 'pending',
    responded_at REAL,
    captcha_text TEXT,
    captcha_passed INTEGER NOT NULL DEFAULT 0,
    delivered INTEGER NOT NULL DEFAULT 0,
    is_sub INTEGER NOT NULL DEFAULT 0,
    is_vip INTEGER NOT NULL DEFAULT 0,
    is_mod INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (sorteio_id) REFERENCES sorteios(id)
);

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    actor TEXT,         -- 'admin' ou 'system' ou 'chat'
    action TEXT,        -- ex: 'start_giveaway', 'change_mult', 'draw_winner'
    payload TEXT        -- JSON com detalhes
);

CREATE TABLE IF NOT EXISTS roleta_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    nick TEXT,
    winner TEXT,
    prize TEXT,
    spin_index INTEGER
);

CREATE INDEX IF NOT EXISTS idx_winners_drawn_at ON winners(drawn_at);
CREATE INDEX IF NOT EXISTS idx_winners_username ON winners(username);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts);
"""


_lock = asyncio.Lock()


async def init() -> None:
    """Cria as tabelas se não existirem. Idempotente."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()
    # Migração leve: adiciona colunas is_sub/is_vip/is_mod em winners se faltar
    async with aiosqlite.connect(DB_PATH) as db:
        for col in ('is_sub', 'is_vip', 'is_mod'):
            try:
                await db.execute(f'ALTER TABLE winners ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0')
                await db.commit()
            except Exception:
                pass  # coluna já existe
        cur = await db.execute('PRAGMA table_info(winners)')
        cols = {row[1] for row in await cur.fetchall()}
        await cur.close()
        if 'outcome' not in cols:
            # Preserva os ganhadores antigos e identifica a causa quando o log
            # registrou explicitamente timeout, desistência ou pulo manual.
            await db.execute("ALTER TABLE winners ADD COLUMN outcome TEXT NOT NULL DEFAULT 'pending'")
            await db.execute("UPDATE winners SET outcome='answered' WHERE answered=1")
            cur = await db.execute('SELECT id, platform, username, drawn_at FROM winners ORDER BY drawn_at, id')
            historical = await cur.fetchall()
            await cur.close()
            by_user = {}
            for winner_id, platform, username, drawn_at in historical:
                by_user.setdefault((platform.casefold(), username.casefold()), []).append((drawn_at, winner_id))
            cur = await db.execute("SELECT ts, payload FROM audit WHERE action='skip_winner' ORDER BY ts")
            skips = await cur.fetchall()
            await cur.close()
            outcomes = {'timeout': 'timeout', 'chat_voluntary': 'declined', 'manual': 'skipped'}
            for ts, payload in skips:
                try:
                    detail = json.loads(payload or '{}')
                    identity = (str(detail['platform']).casefold(), str(detail['username']).casefold())
                    entries = by_user.get(identity, [])
                    index = bisect_right(entries, (ts, float('inf'))) - 1
                    outcome = outcomes.get(detail.get('reason'), 'skipped')
                    if index >= 0:
                        await db.execute("UPDATE winners SET outcome=? WHERE id=? AND outcome='pending'",
                                         (outcome, entries[index][1]))
                except (ValueError, TypeError, KeyError):
                    continue  # eventos antigos incompletos não são inventados
            await db.commit()
        # Migração: adiciona coluna nick em roleta_history se faltar
        try:
            await db.execute('ALTER TABLE roleta_history ADD COLUMN nick TEXT')
            await db.commit()
        except Exception:
            pass  # coluna já existe
    logger.info(f'Banco inicializado: {DB_PATH}')


async def backup_now(reason: str = 'auto') -> Path | None:
    """Faz um backup do banco (arquivo .db -> .db.bak-<ts>)."""
    if not DB_PATH.exists():
        return None
    try:
        ts = datetime.now().strftime('%Y%m%d-%H%M%S')
        target = BACKUP_DIR / f'sorteador-{ts}-{reason}.db'
        # SQLite pode estar sendo escrito; usa 'copy' em vez de open
        shutil.copy2(DB_PATH, target)
        # Mantém só os últimos 10
        backups = sorted(BACKUP_DIR.glob('sorteador-*.db'))
        for old in backups[:-10]:
            old.unlink(missing_ok=True)
        return target
    except Exception as e:
        logger.warning(f'Falha no backup: {e}')
        return None


# ==============================================================================
# 💾 CONFIG (chave/valor em JSON)
# ==============================================================================
async def config_set(key: str, value: Any) -> None:
    """Salva um valor de configuração."""
    async with _lock:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'INSERT INTO config(key, value) VALUES(?, ?) '
                'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                (key, json.dumps(value, ensure_ascii=False)),
            )
            await db.commit()


async def config_get(key: str, default: Any = None) -> Any:
    """Lê um valor de configuração."""
    async with _lock:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute('SELECT value FROM config WHERE key=?', (key,))
            row = await cur.fetchone()
            await cur.close()
    if not row:
        return default
    try:
        return json.loads(row[0])
    except (ValueError, TypeError):
        return default


async def config_get_all() -> dict:
    """Retorna todas as configs como dict."""
    async with _lock:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute('SELECT key, value FROM config')
            rows = await cur.fetchall()
            await cur.close()
    out = {}
    for k, v in rows:
        try:
            out[k] = json.loads(v)
        except (ValueError, TypeError):
            out[k] = v
    return out


# ==============================================================================
# 🎰 ROLETA
# ==============================================================================
async def roleta_list() -> list[dict]:
    async with _lock:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                'SELECT id, name, weight, active, icon FROM roleta ORDER BY id'
            )
            rows = await cur.fetchall()
            await cur.close()
    return [
        {'id': r[0], 'name': r[1], 'weight': r[2], 'active': bool(r[3]), 'icon': r[4]}
        for r in rows
    ]


async def roleta_upsert(item: dict) -> int:
    """Cria ou atualiza um item. Retorna o id."""
    async with _lock:
        async with aiosqlite.connect(DB_PATH) as db:
            if item.get('id'):
                await db.execute(
                    'UPDATE roleta SET name=?, weight=?, active=?, icon=? WHERE id=?',
                    (item['name'], item['weight'], int(item.get('active', 1)),
                     item.get('icon', '🎁'), item['id']),
                )
                await db.commit()
                return int(item['id'])
            cur = await db.execute(
                'INSERT INTO roleta(name, weight, active, icon, created_at) '
                'VALUES(?, ?, ?, ?, ?)',
                (item['name'], item['weight'], int(item.get('active', 1)),
                 item.get('icon', '🎁'), time.time()),
            )
            await db.commit()
            new_id = cur.lastrowid
            await cur.close()
            return new_id


async def roleta_delete(item_id: int) -> None:
    async with _lock:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('DELETE FROM roleta WHERE id=?', (item_id,))
            await db.commit()


# ==============================================================================
# 🏆 SORTEIOS E VENCEDORES
# ==============================================================================
async def sorteio_create(keyword: str) -> int:
    async with _lock:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                'INSERT INTO sorteios(started_at, keyword, status) VALUES(?,?,?)',
                (time.time(), keyword, 'open'),
            )
            await db.commit()
            new_id = cur.lastrowid
            await cur.close()
            return new_id


async def sorteio_update(sorteio_id: int, **fields) -> None:
    if not fields:
        return
    sets = ', '.join(f'{k}=?' for k in fields)
    vals = list(fields.values()) + [sorteio_id]
    async with _lock:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(f'UPDATE sorteios SET {sets} WHERE id=?', vals)
            await db.commit()


async def winner_insert(w: dict, sorteio_id: int | None = None) -> int:
    async with _lock:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                'INSERT INTO winners(sorteio_id, platform, username, user_id, '
                'weight, chance_pct, award, drawn_at, captcha_text, '
                'is_sub, is_vip, is_mod) '
                'VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (sorteio_id, w['platform'], w['username'], w.get('user_id', ''),
                 w.get('weight', 1.0), w.get('chance_pct', 0.0),
                 w.get('award', ''), w.get('drawn_at', time.time()),
                 w.get('captcha_text', ''),
                 int(bool(w.get('is_sub', False))),
                 int(bool(w.get('is_vip', False))),
                 int(bool(w.get('is_mod', False)))),
            )
            await db.commit()
            new_id = cur.lastrowid
            await cur.close()
            return new_id


async def winner_update(winner_db_id: int, **fields) -> None:
    if not fields:
        return
    # converte bool em int
    for k in ('answered', 'captcha_passed', 'delivered'):
        if k in fields and isinstance(fields[k], bool):
            fields[k] = int(fields[k])
    sets = ', '.join(f'{k}=?' for k in fields)
    vals = list(fields.values()) + [winner_db_id]
    async with _lock:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(f'UPDATE winners SET {sets} WHERE id=?', vals)
            await db.commit()


async def winners_list(limit: int = 100, username: str | None = None) -> list[dict]:
    q = 'SELECT id, sorteio_id, platform, username, user_id, weight, chance_pct, ' \
        'award, drawn_at, answered, responded_at, captcha_text, captcha_passed, ' \
        'delivered, is_sub, is_vip, is_mod, outcome FROM winners'
    args: list = []
    if username:
        q += ' WHERE username=? COLLATE NOCASE'
        args.append(username.lower())
    q += ' ORDER BY drawn_at DESC LIMIT ?'
    args.append(limit)
    async with _lock:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(q, args)
            rows = await cur.fetchall()
            await cur.close()
    return [
        {
            'id': r[0], 'sorteio_id': r[1], 'platform': r[2],
            'username': r[3], 'user_id': r[4], 'weight': r[5],
            'chance_pct': r[6], 'award': r[7], 'drawn_at': r[8],
            'answered': bool(r[9]), 'responded_at': r[10],
            'captcha_text': r[11], 'captcha_passed': bool(r[12]),
            'delivered': bool(r[13]),
            'outcome': r[17],
            'is_sub': bool(r[14]), 'is_vip': bool(r[15]), 'is_mod': bool(r[16]),
        }
        for r in rows
    ]


async def winner_rank(platform: str, username: str) -> dict[str, int]:
    """Estatísticas de todos os sorteios desta plataforma, sem limite de páginas.

    'mamou' significa prazo esgotado; pulo voluntário ou manual é separado.
    Registros antigos sem causa registrada continuam pendentes, não são
    rotulados falsamente como timeout.
    """
    async with _lock:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute('''
                SELECT COUNT(*),
                       COALESCE(SUM(CASE WHEN answered=1 THEN 1 ELSE 0 END), 0),
                       COALESCE(SUM(CASE WHEN outcome='timeout' THEN 1 ELSE 0 END), 0),
                       COALESCE(SUM(CASE WHEN outcome='declined' THEN 1 ELSE 0 END), 0),
                       COALESCE(SUM(CASE WHEN outcome='skipped' THEN 1 ELSE 0 END), 0),
                       COALESCE(SUM(CASE WHEN outcome IN ('pending', 'captcha_pending', 'captcha_failed') THEN 1 ELSE 0 END), 0)
                FROM winners WHERE platform=? COLLATE NOCASE AND username=? COLLATE NOCASE
            ''', (platform, username))
            values = await cur.fetchone()
            await cur.close()
    return dict(zip(('total', 'respondeu', 'mamou', 'desistiu', 'pulou', 'pendente'),
                    (int(value or 0) for value in values)))


async def roleta_history_add(winner: str, prize: str, spin_index: int, nick: str = '') -> None:
    async with _lock:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'INSERT INTO roleta_history(ts, nick, winner, prize, spin_index) VALUES(?,?,?,?,?)',
                (time.time(), nick, winner, prize, spin_index),
            )
            await db.commit()


async def roleta_history_list(limit: int = 50) -> list[dict]:
    async with _lock:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                'SELECT ts, nick, winner, prize, spin_index FROM roleta_history '
                'ORDER BY ts DESC LIMIT ?',
                (limit,),
            )
            rows = await cur.fetchall()
            await cur.close()
    return [{'ts': r[0], 'nick': r[1] or '', 'winner': r[2], 'prize': r[3], 'spin_index': r[4]} for r in rows]


# ==============================================================================
# 📋 AUDIT
# ==============================================================================
async def audit_add(actor: str, action: str, payload: dict | None = None) -> None:
    async with _lock:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'INSERT INTO audit(ts, actor, action, payload) VALUES(?,?,?,?)',
                (time.time(), actor, action, json.dumps(payload or {}, ensure_ascii=False)),
            )
            await db.commit()


async def audit_list(limit: int = 100) -> list[dict]:
    async with _lock:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                'SELECT ts, actor, action, payload FROM audit ORDER BY ts DESC LIMIT ?',
                (limit,),
            )
            rows = await cur.fetchall()
            await cur.close()
    return [
        {'ts': r[0], 'actor': r[1], 'action': r[2], 'payload': json.loads(r[3] or '{}')}
        for r in rows
    ]


# ==============================================================================
# 🔄 EXPORTAR / IMPORTAR HISTÓRICO (CSV)
# ==============================================================================
async def export_winners_csv() -> str:
    """Retorna o conteúdo CSV (com BOM pra Excel)."""
    import csv, io
    winners = await winners_list(limit=10_000)
    buf = io.StringIO()
    buf.write('﻿')  # BOM
    writer = csv.writer(buf, delimiter=';')
    writer.writerow([
        'id', 'data', 'plataforma', 'usuario', 'user_id', 'peso',
        'chance_pct', 'premio', 'respondeu', 'passou_captcha', 'entregue',
    ])
    for w in winners:
        data = datetime.fromtimestamp(w['drawn_at']).strftime('%Y-%m-%d %H:%M:%S')
        writer.writerow([
            w['id'], data, w['platform'], w['username'], w.get('user_id', ''),
            f"{w['weight']:.4f}", f"{w['chance_pct']:.4f}", w.get('award', ''),
            'sim' if w['answered'] else 'nao',
            'sim' if w['captcha_passed'] else 'nao',
            'sim' if w['delivered'] else 'nao',
        ])
    return buf.getvalue()


# ==============================================================================
# 🧹 LIMPAR HISTÓRICO
# ==============================================================================
async def clear_winners() -> None:
    """Apaga todo o histórico de vencedores (com backup antes)."""
    await backup_now('pre-clear-winners')
    async with _lock:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('DELETE FROM winners')
            await db.execute('DELETE FROM roleta_history')
            await db.commit()


async def roleta_save_settings(items: list[dict], config: dict) -> None:
    """Grava prêmios e configurações juntos; falhas revertem a transação inteira."""
    async with _lock:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute('BEGIN IMMEDIATE')
            cursor = await conn.execute('SELECT id FROM roleta')
            ids = {row[0] for row in await cursor.fetchall()}
            submitted = [item['id'] for item in items]
            if len(set(submitted)) != len(submitted) or set(submitted) != ids:
                raise ValueError('A lista de prêmios mudou. Atualize o painel e tente novamente.')
            for item in items:
                await conn.execute('UPDATE roleta SET name=?,weight=?,active=?,icon=? WHERE id=?',
                                   (item['name'], item['weight'], int(item['active']), item['icon'], item['id']))
            for key, value in config.items():
                await conn.execute('INSERT INTO config(key,value) VALUES(?,?) '
                                   'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                                   (key, json.dumps(value, ensure_ascii=False)))
            await conn.execute('INSERT INTO audit(ts,actor,action,payload) VALUES(?,?,?,?)',
                               (time.time(), 'admin', 'roleta_settings_saved', json.dumps({'items': len(items)})))
            await conn.commit()

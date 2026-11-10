"""Teste sem credenciais reais: python tests/verify_rank_and_merge.py."""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    import aiosqlite
except ModuleNotFoundError:
    sys.path.append(str(ROOT / '.venv' / 'Lib' / 'site-packages'))
    import aiosqlite

import httpx

from servidor import db, env_config
from servidor.app import app, full_state, _load_state_from_db
from servidor.chat_manager import ChatManager
from servidor.giveaway import giveaway
from servidor.state import STATE, AppState, add_participant, _default_messages


async def verify():
    with tempfile.TemporaryDirectory(prefix='sorteador-rank-qa-') as directory:
        root = Path(directory)
        db.DB_PATH = root / 'sorteador.db'
        db.BACKUP_DIR = root / 'backups'
        env_config.ENV_PATH = root / '.env'
        STATE.__dict__.clear()
        STATE.__dict__.update(AppState().__dict__)
        # Simula o banco anterior sem a coluna outcome para testar migração.
        old_schema = db.SCHEMA.replace("    outcome TEXT NOT NULL DEFAULT 'pending',\n", '')
        async with aiosqlite.connect(db.DB_PATH) as conn:
            await conn.executescript(old_schema)
            for i, answered in enumerate((1, 0, 0, 0, 0), start=1):
                await conn.execute('''INSERT INTO winners(platform, username, user_id, weight,
                    chance_pct, drawn_at, answered) VALUES (?, ?, '', 1, 100, ?, ?)''',
                    ('twitch', 'DArcherMan', float(i * 1000), answered))
            await conn.execute('''INSERT INTO winners(platform, username, user_id, weight,
                chance_pct, drawn_at, answered) VALUES ('kick', 'DArcherMan', '', 1, 100, 6000, 1)''')
            for ts, reason in ((2001, 'timeout'), (3001, 'chat_voluntary'), (4001, 'manual')):
                await conn.execute('INSERT INTO audit(ts, actor, action, payload) VALUES (?, ?, ?, ?)',
                                   (ts, 'admin', 'skip_winner', json.dumps({
                                       'platform': 'twitch', 'username': 'DArcherMan', 'reason': reason,
                                   })))
            await conn.commit()
        await db.init()
        await db.init()  # idempotência
        stats = await db.winner_rank('twitch', 'darcherman')
        assert stats == dict(total=5, respondeu=1, mamou=1, desistiu=1, pulou=1, pendente=1), stats
        assert (await db.winner_rank('kick', 'DARCHERMAN'))['total'] == 1
        assert (await db.winner_rank('twitch', 'sem_sorte'))['total'] == 0

        # Textos personalizados existentes são mantidos; campos vazios ganham padrão.
        await db.config_set('message_templates', {
            'winner_declined': {'twitch': '', 'kick': 'Mensagem especial personalizada'},
            'nick_lookup': {'twitch': '  ', 'kick': ''},
            'rank_lookup': {'twitch': '', 'kick': ''},
        })
        await _load_state_from_db()
        assert STATE.message_templates['winner_declined']['twitch'] == _default_messages()['winner_declined']['twitch']
        assert STATE.message_templates['winner_declined']['kick'] == 'Mensagem especial personalizada'
        assert STATE.message_templates['rank_lookup']['twitch'].startswith('🏆')

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url='http://localhost') as client:
            config = {'skip_enabled': True, 'skip_command': '!pular', 'skip_limit': 3,
                      'nick_enabled': True, 'nick_command': '!nick',
                      'rank_enabled': True, 'rank_command': '!rank'}
            r = await client.post('/api/chat/commands/config', json=config)
            assert r.status_code == 200, r.text
            assert (await db.config_get('viewer_commands'))['rank_command'] == '!rank'
            assert (await client.post('/api/chat/commands/config', json={**config, 'rank_command': '!nick'})).status_code == 400
            assert (await client.post('/api/chat/commands/config', json={**config, 'rank_command': '!roleta'})).status_code == 400
            assert (await client.post('/api/giveaway/start', json={'keyword': '!rank'})).status_code == 400
            assert (await client.post('/api/giveaway/start', json={'keyword': '!juntar'})).status_code == 200

            add_participant('twitch', 'Alice')
            add_participant('kick', 'Bob', weight=3)
            participants = (await client.get('/api/state')).json()['participants']
            assert round(next(p['chance_pct'] for p in participants if p['username'] == 'Alice'), 2) == 25.0
            assert round(next(p['chance_pct'] for p in participants if p['username'] == 'Bob'), 2) == 75.0
            await client.post('/api/giveaway/participants/toggle', json={'platform': 'kick', 'username': 'Bob'})
            participants = (await client.get('/api/state')).json()['participants']
            assert next(p['chance_pct'] for p in participants if p['username'] == 'Bob') == 0.0
            assert next(p['chance_pct'] for p in participants if p['username'] == 'Alice') == 100.0

            messages = {event: value for event, value in STATE.message_templates.items()}
            messages['winner_declined'] = {'twitch': '', 'kick': 'Mensagem especial personalizada'}
            saved = await client.post('/api/bots/settings', json={'events': {'rank_lookup': True},
                'templates': messages})
            assert saved.status_code == 200, saved.text
            assert STATE.message_templates['winner_declined']['twitch'] == _default_messages()['winner_declined']['twitch']

        # Diferencia respostas e timeouts também em sorteios novos.
        await giveaway.draw()
        await giveaway.answer()
        rank_now = await db.winner_rank('twitch', 'Alice')
        assert rank_now['total'] == 1 and rank_now['respondeu'] == 1
        await giveaway.start('!novo')
        add_participant('twitch', 'Alice')
        await giveaway.draw()
        await giveaway.skip(reason='chat_voluntary')
        assert (await db.winner_rank('twitch', 'Alice'))['desistiu'] == 1
        await giveaway.start('!outro')
        add_participant('twitch', 'Alice')
        await giveaway.draw()
        winner = STATE.current_winner
        giveaway._cancel_timer()
        STATE.winner_deadline = time.time() - 1
        await giveaway._winner_timeout(winner)
        result = await db.winner_rank('twitch', 'Alice')
        assert result == dict(total=3, respondeu=1, mamou=1, desistiu=1, pulou=0, pendente=0), result

        manager = ChatManager()
        manager.announce = AsyncMock()
        message = SimpleNamespace(platform='twitch', username='espectador', message='!rank Alice')
        assert await manager._handle_viewer_command(message) is True
        await asyncio.sleep(.07)
        assert manager.announce.await_args.args[0] == 'rank_lookup'
        assert manager.announce.await_args.kwargs['mamou'] == 1
        assert manager.announce.await_args.kwargs['respondeu'] == 1
        assert manager.announce.await_args.kwargs['nick'] == 'Alice'
        await manager.shutdown()

        html = (ROOT / 'web/admin/index.html').read_text(encoding='utf-8')
        assert 'data-tab="chances"' not in html and 'data-panel="chances"' not in html
        assert 'Chance real' in html and 'viewer-rank-command' in html
        print('Rank: banco legado, causas, plataformas, comandos e mensagens padrão: OK')
        print('Participantes + chances: percentuais e desativação em uma única aba: OK')


if __name__ == '__main__':
    asyncio.run(verify())

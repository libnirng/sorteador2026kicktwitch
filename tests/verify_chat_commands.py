"""Verificação independente de pytest para os novos comandos.

Execute: python tests/verify_chat_commands.py
Usa um banco temporário e não acessa credenciais nem chats reais.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    import aiosqlite  # noqa: F401
except ModuleNotFoundError:
    # Permite testar este projeto no ambiente Linux de QA mesmo com a .venv do Windows.
    sys.path.append(str(ROOT / '.venv' / 'Lib' / 'site-packages'))

import httpx
from servidor import db, env_config, megamu
from servidor.app import app
from servidor.chat_manager import ChatManager
from servidor.giveaway import GiveawayEngine
from servidor.kick_chat import KickMessage
from servidor.state import AppState, STATE, add_participant
from servidor.twitch_chat import TwitchMessage


async def verify():
    with tempfile.TemporaryDirectory(prefix='sorteador-command-qa-') as directory:
        temp = Path(directory)
        db.DB_PATH = temp / 'test.db'
        db.BACKUP_DIR = temp / 'backups'
        env_config.ENV_PATH = temp / '.env'
        STATE.__dict__.clear()
        STATE.__dict__.update(AppState().__dict__)
        await db.init()

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            payload = {'skip_enabled': True, 'skip_command': '!pular', 'skip_limit': 1,
                       'nick_enabled': True, 'nick_command': '!nick'}
            r = await client.post('/api/chat/commands/config', json=payload)
            assert r.status_code == 200, r.text
            assert (await db.config_get('viewer_commands'))['skip_limit'] == 1
            current = (await client.get('/api/state')).json()['viewer_commands']
            assert current['skip_command'] == '!pular' and current['nick_command'] == '!nick'
            messages = {'winner_declined': {
                'twitch': '⏭️ {nome} desistiu ({usos}/{limite}).',
                'kick': '⏭️ {nome} desistiu pelo {comando}.',
            }, 'nick_lookup': {'twitch': 'MEGAMU: {resultado}', 'kick': '{nick}: {resultado}'}}
            r = await client.post('/api/bots/settings', json={
                'events': {'winner_declined': True, 'nick_lookup': True},
                'templates': messages,
            })
            assert r.status_code == 200, r.text
            assert (await db.config_get('message_templates'))['nick_lookup']['twitch'] == 'MEGAMU: {resultado}'
            assert (await client.post('/api/chat/commands/config', json={**payload,'skip_limit': 0})).status_code == 422
            assert (await client.post('/api/chat/commands/config', json={**payload,'nick_command':'!pular'})).status_code == 400

        for platform, cls in [('kick', KickMessage), ('twitch', TwitchMessage)]:
            STATE.__dict__.clear()
            STATE.__dict__.update(AppState().__dict__)
            STATE.skip_chat_limit = 1
            engine = GiveawayEngine()
            manager = ChatManager()
            messages = []
            manager._schedule_announcement = lambda event, **kw: messages.append((event, kw))
            module = importlib.import_module('servidor.giveaway')
            with patch.object(module, 'giveaway', engine):
                await engine.start('!sorteio')
                add_participant(platform, 'ganhador', user_id='42')
                await engine.draw()
                winner = STATE.current_winner
                callback = getattr(manager, '_on_' + platform)
                await callback(cls(username='intruso', user_id='66', message='!pular'))
                assert STATE.current_winner is winner and STATE.skip_chat_uses == 0
                await callback(cls(username='ganhador', user_id='42', message='!PULAR'))
                assert STATE.current_winner is None and STATE.skip_chat_uses == 1
                assert not winner.answered
                assert messages[-1][0] == 'winner_declined'

                await engine.start('!sorteio')
                assert STATE.skip_chat_uses == 0
                STATE.antibot_enabled = True
                STATE.antibot_random_chance = 100
                add_participant(platform, 'ganhador', user_id='42')
                await engine.draw()
                winner = STATE.current_winner
                assert STATE.antibot_challenge
                STATE.skip_chat_uses = 1
                await callback(cls(username='ganhador', user_id='42', message='!pular'))
                assert STATE.current_winner is winner and not winner.answered
                assert STATE.antibot_challenge is not None
                assert messages[-1][0] == 'winner_skip_limit'

                manager.announce = AsyncMock(return_value={platform:{'sent': True}})
                with patch.object(megamu, 'character_info', new=AsyncMock(return_value='Nick darcherman, 10 resets')):
                    await callback(cls(username='ganhador', user_id='42', message='!nick darcherman'))
                    await asyncio.sleep(.08)
                    assert STATE.current_winner is winner
                    assert STATE.antibot_challenge is not None
                    manager.announce.assert_awaited()
                    assert manager.announce.await_args.args[0] == 'nick_lookup'
                await engine.start('!sorteio')
                add_participant(platform, 'ganhador', user_id='42')
                await engine.draw()
                captcha_winner = STATE.current_winner
                assert STATE.antibot_challenge
                await callback(cls(username='ganhador', user_id='42', message='!pular'))
                assert STATE.current_winner is None and STATE.antibot_challenge is None
                assert not captcha_winner.answered and STATE.skip_chat_uses == 1
                await manager.shutdown()

        class FakeClient:
            def __init__(self, **kwargs):
                assert kwargs['follow_redirects'] is False

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def get(self, url, *, params, headers):
                assert url == 'https://megamu.net/getdata.php'
                assert params == {'char':'darcherman','default':'SEUNICK'}
                return type('Response', (), {'status_code':200, 'text':'Nick: darcherman | Resets: 10'})()

        with patch.object(megamu.httpx, 'AsyncClient', FakeClient):
            assert await megamu.character_info('darcherman') == 'Nick: darcherman | Resets: 10'
        print('Comandos !pular e !nick: limite, identidade, mensagens, configurações e API simulada: OK')


if __name__ == '__main__':
    asyncio.run(verify())

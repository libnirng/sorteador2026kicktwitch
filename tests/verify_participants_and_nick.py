"""Teste local sem Twitch/Kick reais: python tests/verify_participants_and_nick.py."""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    import aiosqlite  # noqa: F401
except ModuleNotFoundError:
    sys.path.append(str(ROOT / '.venv' / 'Lib' / 'site-packages'))

import httpx

from servidor import db, env_config, megamu
from servidor.app import app
from servidor.chat_manager import ChatManager
from servidor.giveaway import giveaway
from servidor.state import STATE, AppState, add_participant


class MockMegaMuClient:
    def __init__(self, **kwargs):
        assert kwargs['follow_redirects'] is False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, *, params, headers):
        assert url == 'https://megamu.net/getdata.php'
        assert params['default'] == 'SEUNICK'
        text = ('[DArcherMan] 400(200rr), HuntLevel: 138'
                if params['char'] == 'darcherman' else 'Player não existente.')
        return type('Response', (), {'status_code': 200, 'text': text})()


async def verify():
    with tempfile.TemporaryDirectory(prefix='sorteador-participants-qa-') as directory:
        temp = Path(directory)
        db.DB_PATH = temp / 'test.db'
        db.BACKUP_DIR = temp / 'backups'
        env_config.ENV_PATH = temp / '.env'
        STATE.__dict__.clear()
        STATE.__dict__.update(AppState().__dict__)
        await db.init()
        await giveaway.start('!sorteio')
        add_participant('twitch', 'Alice')
        add_participant('kick', 'Bob')
        assert {p.username for p in giveaway._build_pool()[0]} == {'Alice', 'Bob'}

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url='http://localhost') as client:
            endpoint = '/api/giveaway/participants/toggle'
            payload = {'platform': 'twitch', 'username': 'aLiCe'}
            response = await client.post(endpoint, json=payload)
            assert response.status_code == 200, response.text
            assert response.json()['active'] is False
            current = (await client.get('/api/state')).json()['participants']
            assert next(p for p in current if p['username'] == 'Alice')['active'] is False
            assert [p.username for p in giveaway._build_pool()[0]] == ['Bob']
            assert len(giveaway.compute_chances()) == 1
            # Escrever a palavra-chave outra vez não altera o bloqueio manual.
            assert add_participant('twitch', 'Alice') is False
            assert STATE.participants['twitch:alice'].active is False

            response = await client.post(endpoint, json=payload)
            assert response.status_code == 200, response.text
            assert response.json()['active'] is True
            assert {p.username for p in giveaway._build_pool()[0]} == {'Alice', 'Bob'}
            assert response.json()['active_changed_at'] > 0

            assert (await client.post(endpoint, json={**payload, 'username': 'not-here'})).status_code == 404
            assert (await client.post(endpoint, json={'platform': 'unknown', 'username': 'Alice'})).status_code == 422
            # Na seleção em andamento, não se pode mudar o status do vencedor atual.
            await client.post(endpoint, json=payload)  # Alice inativa novamente
            await giveaway.draw()
            assert STATE.current_winner.username == 'Bob'
            assert (await client.post(endpoint, json={'platform': 'kick', 'username': 'Bob'})).status_code == 409

            await giveaway.reset()
            await giveaway.start('!novo')
            add_participant('twitch', 'Alice')
            assert STATE.participants['twitch:alice'].active is True  # nova coleta

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=('203.0.113.2', 1234)),
            base_url='http://localhost',
        ) as remote:
            assert (await remote.post('/api/giveaway/participants/toggle',
                                      json={'platform': 'twitch', 'username': 'Alice'})).status_code == 403

        with patch.object(megamu.httpx, 'AsyncClient', MockMegaMuClient):
            text = await megamu.character_info('darcherman')
            assert '✅ DArcherMan existe no MEGAMU' in text, text
            assert '400' in text and '200 RR' in text and 'Hunt 138' in text
            try:
                await megamu.character_info('personagem_inexistente')
                raise AssertionError('Um personagem inexistente não pode ser confirmado.')
            except ValueError as error:
                assert 'não existe' in str(error)

            manager = ChatManager()
            manager.announce = AsyncMock()
            await manager._answer_nick_lookup('twitch', 'espectador', 'darcherman')
            assert manager.announce.await_args.args[0] == 'nick_lookup'
            await manager._answer_nick_lookup('kick', 'espectador', 'naoexiste')
            assert manager.announce.await_args.args[0] == 'nick_lookup_error'
            assert 'não existe' in manager.announce.await_args.kwargs['motivo']
        print('Participantes: ativar, desativar, chances, auditoria e bloqueio local: OK')
        print('!nick: confirmação, níveis e inexistente na Twitch e Kick: OK')


if __name__ == '__main__':
    asyncio.run(verify())

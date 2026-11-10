"""Comandos de chat de desistência e consulta pública MegaMu."""

import asyncio
import importlib
from unittest.mock import AsyncMock

import httpx
import pytest

from test_regressions import isolated, run  # fixture com estado e banco isolados
from servidor import db, megamu
from servidor.app import app
from servidor.chat_manager import ChatManager
from servidor.giveaway import GiveawayEngine
from servidor.state import STATE, add_participant
from servidor.kick_chat import KickMessage
from servidor.twitch_chat import TwitchMessage


@pytest.mark.parametrize('platform', ['twitch', 'kick'])
def test_only_the_current_winner_can_skip_and_the_limit_is_global(platform, monkeypatch):
    async def scenario():
        engine = GiveawayEngine()
        monkeypatch.setattr(importlib.import_module('servidor.giveaway'), 'giveaway', engine)
        manager = ChatManager()
        messages = []
        monkeypatch.setattr(manager, '_schedule_announcement', lambda event, **kwargs: messages.append((event, kwargs)))
        STATE.skip_chat_limit = 1
        await engine.start('!sorteio')
        add_participant(platform, 'ganhador', user_id='42')
        await engine.draw()
        winner = STATE.current_winner
        assert winner is not None
        cls = TwitchMessage if platform == 'twitch' else KickMessage
        callback = getattr(manager, '_on_' + platform)

        await callback(cls(username='outro', user_id='88', message='!pular'))
        assert STATE.current_winner is winner and STATE.skip_chat_uses == 0

        await callback(cls(username='ganhador', user_id='42', message='!PULAR'))
        assert STATE.current_winner is None and STATE.skip_chat_uses == 1
        assert not winner.answered and not winner.delivered
        assert any(event == 'winner_declined' for event, _ in messages)

        await engine.start('!sorteio')
        assert STATE.skip_chat_uses == 0
        add_participant(platform, 'ganhador', user_id='42')
        await engine.draw()
        winner = STATE.current_winner
        STATE.skip_chat_uses = STATE.skip_chat_limit
        await callback(cls(username='ganhador', user_id='42', message='!pular'))
        assert STATE.current_winner is winner and not winner.answered
        assert any(event == 'winner_skip_limit' for event, _ in messages)
        await manager.shutdown()

    run(scenario())


@pytest.mark.parametrize('platform', ['twitch', 'kick'])
def test_captcha_is_not_accidentally_confirmed_by_commands(platform, monkeypatch):
    async def scenario():
        engine = GiveawayEngine()
        monkeypatch.setattr(importlib.import_module('servidor.giveaway'), 'giveaway', engine)
        manager = ChatManager()
        monkeypatch.setattr(manager, '_schedule_announcement', lambda *args, **kwargs: None)
        monkeypatch.setattr(megamu, 'character_info', AsyncMock(return_value='Nick: darcherman | Reset: 10'))
        monkeypatch.setattr(manager, 'announce', AsyncMock(return_value={platform: {'sent': True}}))
        STATE.antibot_enabled = True
        STATE.antibot_random_chance = 100
        await engine.start('!sorteio')
        add_participant(platform, 'ganhador')
        await engine.draw()
        winner = STATE.current_winner
        assert STATE.antibot_challenge is None
        assert winner.captcha_required and not winner.presence_confirmed
        cls = TwitchMessage if platform == 'twitch' else KickMessage
        callback = getattr(manager, '_on_' + platform)

        await callback(cls(username='ganhador', message='!nick darcherman'))
        await asyncio.sleep(.02)
        assert STATE.current_winner is winner
        manager.announce.assert_awaited()
        assert manager.announce.await_args.args[0] == 'nick_lookup'

        await callback(cls(username='ganhador', message='!pular'))
        assert STATE.current_winner is None
        assert STATE.antibot_challenge is None
        assert not winner.answered
        await manager.shutdown()

    run(scenario())


def test_settings_validate_and_persist(monkeypatch):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            body = {'skip_enabled': True, 'skip_command': '!desistir', 'skip_limit': 5,
                    'nick_enabled': True, 'nick_command': '!personagem'}
            result = await client.post('/api/chat/commands/config', json=body)
            assert result.status_code == 200
            assert STATE.skip_chat_limit == 5 and STATE.skip_chat_command == '!desistir'
            assert (await db.config_get('viewer_commands'))['nick_command'] == '!personagem'
            assert (await client.post('/api/chat/commands/config', json={**body, 'skip_limit': 0})).status_code == 422
            assert (await client.post('/api/chat/commands/config', json={**body, 'nick_command': '!desistir'})).status_code == 400
            assert (await client.post('/api/chat/commands/config', json={**body, 'nick_command': '!roleta'})).status_code == 400

    run(scenario())


def test_megamu_character_uses_public_getdata_with_encoded_nick(monkeypatch):
    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs['timeout'] == 8 and kwargs['follow_redirects'] is False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, *, params, headers):
            assert url == 'https://megamu.net/getdata.php'
            assert params == {'char': 'darcherman', 'default': 'SEUNICK'}
            return type('Response', (), {'status_code': 200, 'text': 'Nick: darcherman | Resets: 10'})()

    monkeypatch.setattr(megamu.httpx, 'AsyncClient', FakeClient)
    assert run(megamu.character_info('darcherman')) == 'Nick: darcherman | Resets: 10'
    with pytest.raises(ValueError):
        run(megamu.character_info('nick&key=segredo'))

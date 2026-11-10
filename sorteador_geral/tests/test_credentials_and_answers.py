import asyncio
import importlib
import time
from unittest.mock import Mock

import httpx
import pytest

from test_regressions import isolated, run
from servidor import db, env_config, kick_oauth
from servidor.state import STATE, AppState, add_participant
from servidor.giveaway import GiveawayEngine
from servidor.chat_manager import ChatManager
from servidor.twitch_chat import TwitchMessage
from servidor.kick_chat import KickMessage
from servidor.app import app, _load_state_from_db, full_state


def test_env_preserves_special_characters_and_blank_form_keeps_saved_token():
    async def scenario():
        env_config.update({'OTHER_SETTING': 'texto # com = e "aspas"\nnova linha'})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            assert (await client.post('/api/twitch/helix/save', json={'client_id':'app-id','oauth':'oauth:private-test-token'})).status_code == 200
            assert (await client.post('/api/twitch/helix/save', json={'client_id':'app-id','oauth':''})).status_code == 200
            assert STATE.bot_twitch_oauth == 'oauth:private-test-token'
            saved = env_config.read()
            assert saved['TWITCH_ACCESS_TOKEN'] == STATE.bot_twitch_oauth
            assert saved['OTHER_SETTING'] == 'texto # com = e "aspas"\nnova linha'
            payload = (await client.get('/api/state')).text
            assert 'private-test-token' not in payload
        # O arquivo também recupera as credenciais quando não existem mais no banco.
        await db.config_set('bot_twitch_oauth','')
        STATE.bot_twitch_oauth = ''
        await _load_state_from_db()
        assert STATE.bot_twitch_oauth == 'oauth:private-test-token'
    run(scenario())


def test_kick_env_session_survives_unavailable_windows_storage_and_logout_removes_it(monkeypatch):
    storage = Mock()
    storage.save_token.return_value = False
    storage.load_token.return_value = None
    monkeypatch.setattr(kick_oauth.secure_storage, 'get_storage', lambda: storage)
    env_config.update({'KICK_CLIENT_ID':'test-app','KICK_CLIENT_SECRET':'private-secret'})
    oauth = kick_oauth.KickOAuth('test-app','http://localhost/callback','private-secret')
    oauth._set_tokens_internal('private-access','private-refresh','Bearer',3600,'42','pessoa',['chat:write'])
    expires_at = oauth._expires_at
    assert oauth._save_tokens()
    restored = kick_oauth.setup_oauth('test-app','http://localhost/callback')
    assert restored._access_token == 'private-access' and restored._refresh_token == 'private-refresh'
    assert restored.client_secret == 'private-secret'
    assert restored._expires_at == expires_at and restored.has_chat_write()
    assert 'private-access' not in str(restored.get_full_status())
    restored.clear_tokens()
    assert env_config.kick_tokens() is None
    assert not kick_oauth.setup_oauth('test-app','http://localhost/callback')._access_token


@pytest.mark.parametrize('platform',['kick','twitch'])
def test_reply_confirms_automatically_for_correct_platform_and_identity(platform, monkeypatch):
    async def scenario():
        module = importlib.import_module('servidor.giveaway')
        engine = GiveawayEngine()
        monkeypatch.setattr(module,'giveaway',engine)
        manager = ChatManager()
        await engine.start('!sorteio')
        add_participant(platform,'Pessoa',user_id='42')
        await engine.draw()
        winner = STATE.current_winner
        cls = KickMessage if platform == 'kick' else TwitchMessage
        callback = getattr(manager,'_on_'+platform)
        await callback(cls(username='Pessoa',user_id='999',message='estou aqui'))
        assert STATE.current_winner is winner
        other = 'twitch' if platform == 'kick' else 'kick'
        other_cls = TwitchMessage if other == 'twitch' else KickMessage
        await getattr(manager,'_on_'+other)(other_cls(username='Pessoa',user_id='42',message='estou aqui'))
        assert STATE.current_winner is winner
        await callback(cls(username='PESSOA',user_id='42',message='estou aqui'))
        assert STATE.current_winner is None and STATE.winner_deadline == 0
        assert winner.answered and engine._timer_task is None
    run(scenario())


@pytest.mark.parametrize('platform',['kick','twitch'])
def test_marked_winner_requires_correct_captcha_in_chat(platform, monkeypatch):
    async def scenario():
        module = importlib.import_module('servidor.giveaway')
        engine = GiveawayEngine()
        monkeypatch.setattr(module,'giveaway',engine)
        STATE.antibot_enabled=True
        STATE.antibot_random_chance=100
        await engine.start('!sorteio')
        add_participant(platform,'Pessoa')
        await engine.draw()
        assert STATE.antibot_challenge is None
        manager = ChatManager()
        cls = KickMessage if platform=='kick' else TwitchMessage
        callback = getattr(manager,'_on_'+platform)
        await callback(cls(username='pessoa',message='resposta errada'))
        assert STATE.current_winner is not None
        assert STATE.winner_deadline == 0
        assert STATE.antibot_challenge is not None
        expected = STATE.antibot_challenge['expected']
        await callback(cls(username='pessoa',message=str(expected)))
        assert STATE.current_winner is None and STATE.winner_deadline == 0
        assert STATE.winners[-1].answered
    run(scenario())


def test_timeout_stops_after_each_participant_without_response_even_if_repeat_is_allowed():
    async def scenario():
        engine=GiveawayEngine()
        await engine.start('!sorteio')
        STATE.block_repeat_winner=False
        STATE.auto_advance_timeout=True
        STATE.winner_timer_seconds=.02
        add_participant('kick','pessoa')
        add_participant('twitch','pessoa')
        await engine.draw()
        await asyncio.sleep(.25)
        assert STATE.current_winner is None and STATE.winner_deadline == 0
        assert len(STATE.winners)==2
        await asyncio.sleep(.1)
        assert len(STATE.winners)==2
    run(scenario())


def test_winner_snapshot_contains_official_avatar_even_if_fetch_finishes_after_draw():
    async def scenario():
        engine=GiveawayEngine()
        await engine.start('!sorteio')
        add_participant('twitch','pessoa',user_id='42')
        await engine.draw()
        STATE.participants['twitch:pessoa'].avatar_url='https://example.com/official.png'
        assert full_state()['giveaway']['current_winner']['avatar_url']=='https://example.com/official.png'
        engine._cancel_timer()
    run(scenario())


def test_connected_accounts_announce_by_default_but_explicit_silence_survives_restart():
    async def scenario():
        module=importlib.import_module('servidor.app')
        await module._connected_announcements('kick')
        assert STATE.bot_kick_enabled
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            assert (await client.post('/api/bots/kick/announcements',json={'enabled':False})).status_code==200
        await _load_state_from_db()
        await module._connected_announcements('kick')
        assert not STATE.bot_kick_enabled
        assert env_config.read()['BOT_KICK_ENABLED']=='false'
    run(scenario())

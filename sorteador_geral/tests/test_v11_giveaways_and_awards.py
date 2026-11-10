import asyncio
import importlib
import json
import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from test_regressions import isolated, run
from servidor import antibot, db, env_config, megamu
from servidor.app import app
from servidor.chat_manager import ChatManager
from servidor.giveaway import GiveawayEngine
from servidor.kick_chat import KickMessage
from servidor.twitch_chat import TwitchMessage
from servidor.state import STATE, add_participant


@pytest.mark.parametrize('platform',['twitch','kick'])
def test_first_reply_stops_timer_then_wrong_captcha_waits_for_admin(platform,monkeypatch):
    async def scenario():
        engine=GiveawayEngine()
        monkeypatch.setattr(importlib.import_module('servidor.giveaway'),'giveaway',engine)
        manager=ChatManager();manager.announce=AsyncMock(return_value={})
        STATE.winner_timer_seconds=75;STATE.antibot_timer_seconds=5
        STATE.antibot_enabled=True;STATE.antibot_random_chance=100
        STATE.antibot_max_attempts=1  # comportamento antigo continua selecionável
        await engine.start('!sorteio')
        add_participant(platform,'pessoa')
        await engine.draw()
        winner=STATE.current_winner;deadline=STATE.winner_deadline
        assert 73 < deadline-time.time() <= 75
        assert STATE.antibot_challenge is None
        assert winner.captcha_required and not winner.presence_confirmed
        cls=TwitchMessage if platform=='twitch' else KickMessage
        await getattr(manager,'_on_'+platform)(cls(username='pessoa',message='oi, estou aqui'))
        assert STATE.current_winner is winner and winner.presence_confirmed
        assert STATE.winner_deadline==0 and engine._timer_task is None
        assert STATE.antibot_challenge and STATE.antibot_challenge['deadline']==0
        expected=STATE.antibot_challenge['expected']
        await getattr(manager,'_on_'+platform)(cls(username='pessoa',message='errado'))
        assert STATE.current_winner is winner and STATE.winner_deadline==0
        assert STATE.antibot_challenge is None and winner.captcha_failed
        assert STATE.captcha_feedback['status']=='wrong'
        assert STATE.captcha_feedback['expected']==expected
        await getattr(manager,'_on_'+platform)(cls(username='pessoa',message=str(expected)))
        assert STATE.current_winner is winner  # segunda tentativa bloqueada
        await asyncio.gather(*manager._announcements)
        assert all(call.args[0]=='captcha_fail' for call in manager.announce.call_args_list)
        assert manager.announce.call_args.kwargs['resposta']==expected
        await engine.skip()
        assert STATE.current_winner is None
        assert winner.answered and not winner.delivered

        # Em um novo sorteio, a segunda fala correta confirma o prêmio.
        await engine.start('!sorteio')
        add_participant(platform,'pessoa')
        await engine.draw()
        winner=STATE.current_winner
        await getattr(manager,'_on_'+platform)(cls(username='pessoa',message='presente'))
        correct=STATE.antibot_challenge['expected']
        await getattr(manager,'_on_'+platform)(cls(username='pessoa',message=str(correct)))
        assert winner.answered and STATE.current_winner is None and STATE.winner_deadline==0
        assert winner.captcha_passed
        await asyncio.gather(*manager._announcements)
        assert manager.announce.call_args.args[0]=='captcha_success'
    run(scenario())


def test_manual_next_keeps_five_participants_while_collection_is_paused(monkeypatch):
    async def scenario():
        engine=GiveawayEngine()
        monkeypatch.setattr(importlib.import_module('servidor.app'),'giveaway',engine)
        await engine.start('!sorteio')
        for number in range(5):add_participant('kick','pessoa'+str(number))
        await engine.pause()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            for _ in range(5):
                response=await client.post('/api/giveaway/next',json={})
                assert response.status_code==200,response.text
                await engine.answer()
            assert len(STATE.participants)==5 and len({w.username for w in STATE.winners})==5
            assert STATE.is_paused
            assert (await client.post('/api/giveaway/next',json={})).status_code==400
    run(scenario())


@pytest.mark.parametrize('automatic',[False,True])
def test_timeout_advances_only_when_enabled(automatic):
    async def scenario():
        engine=GiveawayEngine()
        STATE.auto_advance_timeout=automatic
        STATE.winner_timer_seconds=.03
        await engine.start('!sorteio')
        for number in range(2):add_participant('kick','pessoa'+str(number))
        await engine.draw()
        await asyncio.sleep(.25)
        assert len(STATE.winners)==(2 if automatic else 1)
        assert STATE.current_winner is None and STATE.winner_deadline==0
        assert len(STATE.participants)==2
    run(scenario())


@pytest.mark.parametrize('platform',['kick','twitch'])
def test_confirmation_and_repeat_include_current_weighted_chance(platform):
    async def scenario():
        manager=ChatManager();manager.announce=AsyncMock(return_value={})
        STATE.is_running=True;STATE.keyword='!sorteio'
        add_participant(platform,'existente',weight=1)
        cls=KickMessage if platform=='kick' else TwitchMessage
        msg=cls(username='assinante',is_sub=True,message='!sorteio')
        await getattr(manager,'_on_'+platform)(msg)
        await asyncio.gather(*manager._announcements)
        call=manager.announce.call_args
        assert call.args[0]=='entry_accepted' and call.kwargs['chance']=='75.00'
        assert call.kwargs['participantes']==2 and call.kwargs['platform']==platform
        await getattr(manager,'_on_'+platform)(msg)
        await asyncio.gather(*manager._announcements)
        call=manager.announce.call_args
        assert call.args[0]=='entry_repeat' and call.kwargs['chance']=='75.00'
        assert len(STATE.participants)==2
    run(scenario())


def test_message_destination_silences_only_selected_event_on_one_platform():
    async def scenario():
        manager=ChatManager()
        STATE.simulation_mode=False;STATE.bot_kick_enabled=True;STATE.bot_twitch_enabled=True
        STATE.chat_event_platforms={'entry_accepted':{'twitch':False,'kick':True}}
        manager.send=AsyncMock(return_value=True)
        result=await manager.announce('entry_accepted',nome='pessoa',peso='2,5',chance='50.00',participantes=2)
        assert not result['twitch']['sent'] and result['kick']['sent']
        manager.send.assert_awaited_once()
        assert '2,5x' in manager.send.call_args.args[1]
    run(scenario())


def test_megamu_config_query_and_import_keep_key_private_and_existing_weights():
    async def scenario():
        original=httpx.AsyncClient
        requests=[]
        def handler(request):
            requests.append(request)
            assert request.url.host=='megamu.net' and request.url.path=='/dvapi.php'
            assert dict(request.url.params)=={'dv':'my-dv','key':'private-megamu-key','action':'getawards'}
            return httpx.Response(200,json={'result':1,'awards':[{'name':'VIP'},{'name':'Condor Flame'},{'name':'Condor Flame'}]})
        await db.roleta_upsert({'name':'VIP','weight':37,'active':True})
        from servidor import roleta
        await roleta.load_items_from_db()
        async with original(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            response=await client.post('/api/megamu/config',json={'dv':'my-dv','key':'private-megamu-key','enabled':True})
            assert response.status_code==200 and 'private-megamu-key' not in response.text
            assert env_config.read()['MEGAMU_KEY']=='private-megamu-key'
            assert (await client.post('/api/megamu/config',json={'dv':'my-dv','key':'','enabled':True})).status_code==200
            assert env_config.read()['MEGAMU_KEY']=='private-megamu-key'
            with patch('httpx.AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs)):
                response=await client.get('/api/megamu/awards')
                assert response.status_code==200,response.text
                assert [a['name'] for a in response.json()['awards']]==['VIP','Condor Flame']
                assert 'private-megamu-key' not in response.text
                response=await client.post('/api/megamu/import')
                assert response.status_code==200 and response.json()['added']==1
                assert (await client.post('/api/megamu/import')).json()['added']==0
            assert len(requests)==1  # cache do servidor compartilhado com o overlay/importação
            rows=await db.roleta_list()
            assert [(r['name'],r['weight']) for r in rows]==[('VIP',37),('Condor Flame',1)]
            assert 'private-megamu-key' not in (await client.get('/api/state')).text
    run(scenario())


def test_megamu_authentication_failure_is_visible_without_leaking_credentials():
    async def scenario():
        env_config.update({'MEGAMU_DV':'dv','MEGAMU_KEY':'private-key','MEGAMU_ENABLED':'true'})
        original=httpx.AsyncClient
        def handler(request):return httpx.Response(200,json={'result':-101,'message':'private-key'})
        with patch('httpx.AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs)):
            with pytest.raises(ValueError,match='DV ou chave incorretos'):
                await megamu.refresh()
        assert 'private-key' not in megamu.status()['error']
    run(scenario())

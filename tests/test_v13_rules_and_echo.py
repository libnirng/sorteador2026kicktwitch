import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from test_regressions import isolated, run
from servidor import db, env_config, megamu
from servidor.app import app, _load_state_from_db, full_state
from servidor.chat_manager import ChatManager
from servidor.giveaway import GiveawayEngine, giveaway
from servidor.state import STATE, Winner, add_participant, participant_weight
from servidor.kick_chat import KickMessage
from servidor.twitch_chat import TwitchMessage


@pytest.mark.parametrize('platform',['twitch','kick'])
def test_highest_category_and_moderator_permissions_survive_reload(platform):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            assert (await client.post('/api/giveaway/weights',json={p:{'sub':2,'vip':'2,5','mod':'1,5'} for p in ['twitch','kick']})).status_code==200
            assert participant_weight(platform,True,True,True)==2.5
            assert participant_weight(platform,False,False,True)==1.5
            assert participant_weight(platform,False,False,False)==1
            assert (await client.post('/api/permissions',json={'platform_mods':{'twitch':True,'kick':False}})).status_code==200
            await _load_state_from_db()
            assert STATE.platform_mods=={'twitch':True,'kick':False}
            assert participant_weight(platform,True,True,True)==2.5
            engine=GiveawayEngine();await engine.start('!salva')
            assert await db.config_get('keyword')=='!salva'
            add_participant(platform,'mod',is_mod=True,weight=participant_weight(platform,False,False,True))
            eligible,_=engine._build_pool()
            assert bool(eligible)==(platform=='twitch')
            engine._cancel_timer()
    run(scenario())


@pytest.mark.parametrize('platform',['twitch','kick'])
def test_bot_echo_during_send_and_duplicate_wrong_message_do_not_loop(platform):
    async def scenario():
        STATE.simulation_mode=False;STATE.is_running=True
        STATE.bot_twitch_enabled=STATE.bot_kick_enabled=True
        STATE.current_winner=Winner(platform,'principal','42',1,100,'Premio',time.time(),
            captcha_required=True,presence_confirmed=True,answered=True)
        STATE.winner_deadline=0
        STATE.antibot_challenge={'expected':'ABC','deadline':0,'type':'code','attempts':0}
        manager=ChatManager();manager.twitch.user_id='42'
        cls=TwitchMessage if platform=='twitch' else KickMessage
        callback=getattr(manager,'_on_'+platform)
        checked=[]
        def check(text):
            checked.append(text)
            return text=='ABC','wrong' if text!='ABC' else 'correct'
        async def send(text):
            # The event can arrive BEFORE the send API returns its message id.
            await callback(cls(username='principal',user_id='42',message=text,message_id='echo-'+str(len(checked))))
            return {'success':True,'message_id':'sent'} if platform=='twitch' else True
        getattr(manager,platform).send_message=send
        manager.kick.last_sent_message_id='sent'
        oauth=SimpleNamespace(get_user_info=lambda:('42','principal'))
        with patch('servidor.kick_oauth.get_oauth',return_value=oauth),patch('servidor.antibot.check',side_effect=check),patch.object(giveaway,'answer',AsyncMock()) as answer:
            wrong=cls(username='principal',user_id='42',message='errada',message_id='user-1')
            await callback(wrong)
            if manager._announcements:await asyncio.gather(*manager._announcements)
            await callback(wrong)
            assert checked==['errada'] and not answer.called
            # Um código só pode ser reenviado se o operador gerar novo desafio.
            STATE.current_winner.captcha_failed = False
            STATE.antibot_challenge={'expected':'ABC','deadline':0,'type':'code','attempts':0}
            # A real message from that same account is still processed.
            await callback(cls(username='principal',user_id='42',message='ABC',message_id='user-2'))
            if manager._announcements:await asyncio.gather(*manager._announcements)
            assert checked==['errada','ABC']
            answer.assert_awaited_once()
    run(scenario())


def test_megamu_save_refreshes_catalog_immediately_and_shared_obs_state():
    async def scenario():
        def response(request):
            assert request.url.params['dv']=='test' and request.url.params['key']=='private'
            return httpx.Response(200,json={'result':1,'awards':[{'name':'Prêmio API'}]})
        original=httpx.AsyncClient
        async with original(transport=httpx.ASGITransport(app=app,client=('127.0.0.1',1111)),base_url='http://test') as client:
            with patch('servidor.megamu.httpx.AsyncClient',lambda **kw:original(transport=httpx.MockTransport(response),**kw)):
                saved=await client.post('/api/megamu/config',json={'dv':'test','key':'private','enabled':True})
            assert saved.status_code==200
            state=full_state()
            assert state['giveaway']['prizes'][0]['name']=='Prêmio API'
            assert env_config.read()['MEGAMU_KEY']=='private'
            assert 'private' not in str(state)
    run(scenario())

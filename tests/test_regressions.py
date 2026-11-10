"""Regressões com SQLite temporário e APIs externas simuladas. python -m pytest -q"""
import asyncio
import base64
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from servidor import db, roleta, kick_oauth
from servidor.app import app, api_roleta_spin, RoletaSpinRequest
from servidor.state import STATE, AppState, RoletaItem, Winner
from servidor.chat_manager import ChatManager
from servidor.twitch_chat import TwitchMessage, TwitchChat
from servidor.kick_chat import KickMessage, KickChat
from servidor.kick_webhook import KickWebhookValidator

@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    from servidor import env_config
    monkeypatch.setattr(env_config, 'ENV_PATH', tmp_path / '.env')
    fresh=AppState()
    STATE.__dict__.clear(); STATE.__dict__.update(fresh.__dict__)
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'test.db')
    monkeypatch.setattr(db,'BACKUP_DIR',tmp_path/'backups')
    monkeypatch.setattr(roleta,'on_change',None)
    asyncio.run(db.init())


def run(coro): return asyncio.run(coro)


def test_config_zero_persist_and_invalid_input():
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            r=await client.post('/api/roleta/config',json={'extra_spins':0,'duration_seconds':.5,'auto_hide':True,'result_seconds':1})
            assert r.status_code==200 and STATE.roleta_extra_spins==0
            assert await db.config_get('roleta_extra_spins')=='0'
            assert (await client.post('/api/roleta/items',json={'name':'bad','weight':-1})).status_code==422
            assert (await client.post('/api/roleta/spin',json={'test_mode':True,'attempts':0})).status_code==422
    run(scenario())


def test_appearance_persists_and_validates():
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
            assert (await c.post('/api/appearance',json={'wheel_gold':'#abcdef','wheel_size':650})).status_code==200
            assert (await db.config_get('appearance'))['wheel_gold']=='#abcdef'
            assert (await c.post('/api/appearance',json={'wheel_gold':'red;display:none'})).status_code==422
    run(scenario())


def test_sequence_idempotent_finish_cancel_and_hide():
    async def scenario():
        STATE.roleta_items=[RoletaItem(1,'VIP',100)]
        STATE.roleta_duration_seconds=.01; STATE.roleta_result_seconds=.02
        await api_roleta_spin(RoletaSpinRequest(test_mode=True,attempts=2))
        first=STATE.roleta_current_spin_id
        with pytest.raises(Exception) as e:
            await api_roleta_spin(RoletaSpinRequest(test_mode=True))
        assert e.value.status_code==409
        await roleta.mark_finished(); await roleta.mark_finished()  # two OBS sources
        await asyncio.sleep(.06)
        assert STATE.roleta_current_spin_id>first and STATE.roleta_remaining==0
        await roleta.mark_finished(); await asyncio.sleep(.06)
        assert not STATE.roleta_visible and not STATE.roleta_spinning
        await api_roleta_spin(RoletaSpinRequest(test_mode=True,attempts=3))
        await roleta.set_visible(False); await asyncio.sleep(.06)
        assert STATE.roleta_remaining==0 and STATE.roleta_active_spin is None
        assert len(await db.roleta_history_list())==3
    run(scenario())


def test_fallback_without_obs():
    async def scenario():
        STATE.roleta_items=[RoletaItem(1,'VIP',100)]
        STATE.roleta_duration_seconds=.01;STATE.roleta_result_seconds=.01
        await roleta.spin();id=STATE.roleta_current_spin_id
        await roleta._complete_later(id)
        await asyncio.sleep(.05)
        assert not STATE.roleta_spinning and not STATE.roleta_visible
    run(scenario())


def test_normalization_inactive_and_zero():
    STATE.roleta_items=[RoletaItem(1,'off',99,False),RoletaItem(2,'A',0),RoletaItem(3,'B',0)]
    items=roleta.normalized_items()
    assert [x.weight for x in items]==[99,50,50]
    for _ in range(30): assert roleta._pick_weighted()[0] in (1,2)

@pytest.mark.parametrize('platform',['twitch','kick'])
def test_chat_overlay_command_restricted(platform):
    async def scenario():
        manager=ChatManager()
        callback=getattr(manager,'_on_'+platform)
        cls=TwitchMessage if platform=='twitch' else KickMessage
        await callback(cls(username='viewer',message='!roleta'))
        assert not STATE.roleta_visible
        await callback(cls(username='moderator',message='!roleta',is_mod=True))
        assert STATE.roleta_visible
        await callback(cls(username='moderator',message='!roleta ocultar',is_mod=True))
        assert not STATE.roleta_visible
    run(scenario())

@pytest.mark.parametrize('platform',['twitch','kick'])
def test_chat_silence_and_event_switch(platform):
    async def scenario():
        manager=ChatManager();STATE.simulation_mode=False
        target=getattr(manager,platform)
        target.send_message=AsyncMock(return_value={'success':True} if platform=='twitch' else True)
        await manager.announce('winner_announced',nome='Pessoa')
        target.send_message.assert_not_called()
        setattr(STATE,'bot_'+platform+'_enabled',True)
        await manager.announce('winner_announced',nome='Pessoa')
        assert target.send_message.call_count==1
        STATE.chat_events['winner_announced']=False
        await manager.announce('winner_announced',nome='Pessoa')
        assert target.send_message.call_count==1
    run(scenario())


def test_kick_rest_send_confirms_delivery():
    async def scenario():
        oauth=SimpleNamespace(ensure_valid_token=AsyncMock(return_value=(True,'fake-token')),has_chat_write=lambda:True,get_channel_info=lambda:SimpleNamespace(broadcaster_user_id='42'))
        def handler(req):
            assert req.url.path=='/public/v1/chat'
            assert json.loads(req.content)=={'type':'user','broadcaster_user_id':42,'content':'Teste'}
            return httpx.Response(200,json={'data':{'is_sent':True}})
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch.object(kick_oauth,'get_oauth',return_value=oauth),patch('servidor.kick_chat.httpx.AsyncClient',return_value=client):
            assert await KickChat().send_message('Teste')
    run(scenario())


def test_signed_kick_webhook_timestamp_tampering_and_dedup():
    async def scenario():
        validator=KickWebhookValidator();private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        pem=private.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        validator._public_key_cache.get_key=AsyncMock(return_value=pem)
        from datetime import datetime,timezone
        timestamp=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
        body=json.dumps({'broadcaster':{'user_id':42},'sender':{'user_id':8,'username':'pessoa'},'content':'!sorteio'}).encode()
        data=b'id.'+timestamp.encode()+b'.'+body
        signature=base64.b64encode(private.sign(data,padding.PKCS1v15(),hashes.SHA256())).decode()
        headers={'Kick-Event-Message-Id':'id','Kick-Event-Message-Timestamp':timestamp,'Kick-Event-Type':'chat.message.sent','Kick-Event-Signature':signature}
        assert not (await validator.validate_event(headers,body+b'x'))[0]
        ok,error,event=await validator.validate_event(headers,body)
        assert ok,error
        assert event.message_content=='!sorteio'
        assert not (await validator.validate_event(headers,body))[0]
        assert not (await validator.validate_timestamp('2020-01-01T00:00:00Z'))[0]
    run(scenario())


def test_templates_reject_unknown_fields():
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
            assert (await c.post('/api/bots/settings',json={'templates':{'prize_won':{'kick':'{nome.__class__}'}}})).status_code==400
            r=await c.post('/api/bots/settings',json={'twitch_enabled':True,'events':{'prize_won':False},'templates':{'prize_won':{'kick':'{nome}: {premio}'}}})
            assert r.status_code==200
            assert (await db.config_get('bots'))['twitch_enabled']
    run(scenario())


def test_twitch_reconnect_returns_new_socket():
    async def scenario():
        client=TwitchChat();new=SimpleNamespace(recv=AsyncMock(return_value=json.dumps({'metadata':{'message_type':'session_welcome'},'payload':{'session':{'id':'next','keepalive_timeout_seconds':15}}})),close=AsyncMock())
        old=SimpleNamespace(close=AsyncMock())
        with patch('servidor.twitch_chat.websockets.connect',AsyncMock(return_value=new)):
            assert await client._handle_reconnect(0,'wss://test',old)==(new,15)
            old.close.assert_awaited_once()
    run(scenario())


def test_kick_oauth_saved_metadata_does_not_extend_expiry():
    from servidor.kick_oauth import KickOAuth,ChannelInfo
    from unittest.mock import Mock
    oauth=KickOAuth('client','http://localhost/callback')
    oauth._storage=Mock();oauth._access_token='fake';oauth._expires_at=time.time()-10
    oauth._granted_scopes=['user:read','channel:read','chat:write','events:subscribe']
    oauth._channel_info=ChannelInfo('42','pessoa')
    oauth._save_tokens()
    saved=oauth._storage.save_token.call_args.kwargs
    oauth._storage.load_token.return_value={**saved,**saved['metadata']}
    oauth._channel_info=None;oauth._granted_scopes=[]
    assert oauth.load_saved_tokens()
    assert not oauth.has_valid_token()
    assert oauth.has_chat_write() and oauth.get_channel_info().broadcaster_user_id=='42'


def test_broadcaster_can_control_roleta():
    async def scenario():
        from servidor.twitch_chat import _parse_notification
        msg=_parse_notification({'chatter_user_login':'dono','message':{'text':'!roleta'},'badges':[{'set_id':'broadcaster'}]})
        await ChatManager()._on_twitch(msg)
        assert STATE.roleta_visible
        await roleta.set_visible(False)
    run(scenario())


def test_twitch_reads_notifications_after_reconnect():
    async def scenario():
        def message(kind,payload): return json.dumps({'metadata':{'message_type':kind,'subscription_type':'channel.chat.message','message_id':kind},'payload':payload})
        welcome=message('session_welcome',{'session':{'id':'session','keepalive_timeout_seconds':10}})
        old=SimpleNamespace(recv=AsyncMock(side_effect=[welcome,message('session_reconnect',{'session':{'reconnect_url':'wss://next'}})]),close=AsyncMock())
        new=SimpleNamespace(recv=AsyncMock(side_effect=[welcome,message('notification',{'event':{'chatter_user_login':'pessoa','message':{'text':'!sorteio'}}}),message('revocation',{'subscription':{'status':'authorization_revoked'}})]),close=AsyncMock())
        client=TwitchChat();client.broadcaster_id='42';client.user_id='8';client._should_run=True;client._subscribe_chat=AsyncMock();client._on_message=AsyncMock()
        with patch('servidor.twitch_chat.websockets.connect',AsyncMock(side_effect=[old,new])):
            await client._connect_once(0)
        assert client._on_message.await_count==1
        assert client._on_message.call_args.args[0].username=='pessoa'
        client._subscribe_chat.assert_awaited_once()
    run(scenario())


def test_kick_subscription_response_shapes_and_delete_endpoint():
    async def scenario():
        from servidor.kick_subscriptions import KickSubscriptions
        oauth=SimpleNamespace(client_id='client',_granted_scopes=['events:subscribe'],ensure_valid_token=AsyncMock(return_value=(True,'fake')))
        def handler(req):
            assert req.url.path=='/public/v1/events/subscriptions'
            if req.method=='GET':
                return httpx.Response(200,json={'data':[{'id':'sub','event':'chat.message.sent','version':1}]})
            if req.method=='POST':
                return httpx.Response(200,json={'data':[{'subscription_id':'sub','name':'chat.message.sent','version':1,'error':''}]})
            assert req.method=='DELETE' and req.url.params['id']=='sub'
            return httpx.Response(204)
        def factory(**kwargs): return original_client(transport=httpx.MockTransport(handler))
        original_client=httpx.AsyncClient
        with patch.object(kick_oauth,'get_oauth',return_value=oauth),patch('servidor.kick_subscriptions.httpx.AsyncClient',side_effect=factory):
            subs=KickSubscriptions()
            result=await subs.list();assert result.success and result.subscriptions[0].name=='chat.message.sent'
            result=await subs.create('https://example.com/api/webhooks/kick');assert result.success and result.subscription.id=='sub'
            assert (await subs.delete('sub')).success
    run(scenario())


def test_connect_real_twitch_exits_simulation(monkeypatch):
    async def scenario():
        import importlib
        module=importlib.import_module('servidor.app')
        STATE.bot_twitch_client_id='client';STATE.bot_twitch_oauth='fake'
        monkeypatch.setattr(module.chat,'connect_twitch',AsyncMock())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
            assert (await c.post('/api/chat/twitch/connect',json={'channel':'pessoa'})).status_code==200
            assert STATE.simulation_mode is False
            assert await db.config_get('simulation_mode') is False
    run(scenario())


def test_kick_config_redirect_and_auth_reference():
    async def scenario():
        from servidor.kick_chat_auth import get_kick_auth
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
            r=await c.post('/api/oauth/kick/config',json={'client_id':'fake','redirect_uri':'http://localhost:8777/api/oauth/kick/callback'})
            assert r.status_code==200
            assert get_kick_auth()._oauth is kick_oauth.get_oauth()
            assert (await db.config_get('kick_oauth_config'))['redirect_uri'].endswith('/api/oauth/kick/callback')
    run(scenario())


@pytest.mark.parametrize('platform',['twitch','kick'])
def test_antibot_decides_once_on_chat_entry_and_not_duplicate(platform):
    async def scenario():
        from servidor import antibot
        manager=ChatManager();STATE.is_running=True;STATE.keyword='!sorteio'
        STATE.antibot_enabled=True;STATE.antibot_random_chance=50;STATE.captcha_waive_subs_vips=False
        cls=TwitchMessage if platform=='twitch' else KickMessage
        callback=getattr(manager,'_on_'+platform)
        with patch('servidor.antibot.random.random',side_effect=[.49,.50]) as chance:
            await callback(cls(username='marcado',message='!sorteio'))
            await callback(cls(username='livre',message='!sorteio'))
            await callback(cls(username='MARCADO',message='!sorteio'))
            await callback(cls(username='livre',message='!sorteio'))
            assert chance.call_count==2
        assert STATE.participants[f'{platform}:marcado'].captcha_marked
        assert not STATE.participants[f'{platform}:livre'].captcha_marked
        assert len(antibot.marked_participants())==1
        STATE.antibot_random_chance=0
        assert antibot.should_apply_to(STATE.participants[f'{platform}:marcado'])
        assert not antibot.should_apply_to(STATE.participants[f'{platform}:livre'])
    run(scenario())


@pytest.mark.parametrize('chance,random_value,marked',[(0,0,False),(100,.999999,True),(50,.499999,True),(50,.5,False)])
def test_antibot_probability_boundaries(chance,random_value,marked):
    from servidor.state import add_participant
    STATE.antibot_enabled=True;STATE.antibot_random_chance=chance
    with patch('servidor.antibot.random.random',return_value=random_value):
        add_participant('twitch','teste')
    assert STATE.participants['twitch:teste'].captcha_marked is marked


def test_antibot_exemptions_and_disabled_do_not_roll():
    from servidor.state import add_participant
    STATE.antibot_random_chance=100
    with patch('servidor.antibot.random.random') as chance:
        add_participant('twitch','desligado')
        STATE.antibot_enabled=True
        add_participant('kick','assinante',is_sub=True)
        add_participant('twitch','vip',is_vip=True)
        chance.assert_not_called()
    assert STATE.participants['twitch:desligado'].captcha_status=='disabled'
    assert STATE.participants['kick:assinante'].captcha_status=='exempt'
    assert not any(p.captcha_marked for p in STATE.participants.values())


@pytest.mark.parametrize('entry_chance,later_chance,expected',[(0,100,False),(100,0,True)])
def test_winner_uses_entry_decision_and_captcha_deadline(entry_chance,later_chance,expected):
    async def scenario():
        from servidor.giveaway import GiveawayEngine
        from servidor.state import add_participant
        engine=GiveawayEngine();await engine.start('!sorteio')
        STATE.antibot_enabled=True;STATE.captcha_waive_subs_vips=False
        STATE.antibot_random_chance=entry_chance
        STATE.winner_timer_seconds=600;STATE.antibot_timer_seconds=30
        add_participant('twitch','teste')
        STATE.antibot_random_chance=later_chance
        await engine.draw()
        assert STATE.antibot_challenge is None
        assert STATE.current_winner.captcha_required is expected
        if expected:
            assert STATE.participants['twitch:teste'].captcha_status=='marked'
            assert 595 < STATE.winner_deadline-time.time() <= 600
            await engine.confirm_presence()
            assert STATE.participants['twitch:teste'].captcha_status=='challenged'
            assert STATE.winner_deadline == 0
            assert STATE.antibot_challenge['deadline']==0
        else:
            assert STATE.winner_deadline-time.time()>595
        await engine.answer()
    run(scenario())


def test_captcha_list_status_success_failure_and_expiry():
    async def scenario():
        from servidor import antibot
        from servidor.state import add_participant
        STATE.antibot_enabled=True;STATE.antibot_random_chance=100
        add_participant('twitch','teste')
        STATE.current_winner=Winner(platform='twitch',username='teste',user_id='',weight=1,chance_pct=100,award='',drawn_at=time.time())
        challenge=antibot.issue('twitch')
        assert antibot.check(challenge['expected'])[0]
        assert antibot.marked_participants()[0]['status']=='passed'
        antibot.issue('twitch');antibot.check('definitivamente errado');antibot.check('errado')
        assert antibot.marked_participants()[0]['status']=='challenged'
        assert STATE.antibot_challenge['attempts']==2
        antibot.issue('twitch');STATE.antibot_challenge['deadline']=time.time()-1
        assert antibot.check('qualquer')[1]=='expired'
        assert antibot.marked_participants()[0]['status']=='expired'
    run(scenario())


def test_antibot_config_zero_and_new_giveaway_resets_list():
    async def scenario():
        from servidor.giveaway import GiveawayEngine
        from servidor.state import add_participant
        STATE.antibot_enabled=True;STATE.antibot_random_chance=100
        add_participant('kick','teste')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
            r=await c.post('/api/antibot/config',json={'enabled':True,'random_chance':0})
            assert r.status_code==200 and STATE.antibot_random_chance==0
            assert STATE.participants['kick:teste'].captcha_marked
            state=(await c.get('/api/state')).json()
            assert state['antibot']['selection_mode']=='entry'
            assert len(state['antibot']['marked'])==1
            assert 'random_mode' not in state['antibot']
            assert (await c.post('/api/antibot/config',json={'enabled':True,'types':{'math':False,'word':False,'code':False}})).status_code==422
        await GiveawayEngine().start('!novo')
        assert not STATE.participants
        add_participant('kick','teste')
        assert not STATE.participants['kick:teste'].captcha_marked
    run(scenario())


def test_roleta_sequence_keeps_nick_and_numbers_prizes():
    async def scenario():
        STATE.roleta_items=[RoletaItem(1,'VIP',100)];STATE.roleta_result_seconds=.01
        await api_roleta_spin(RoletaSpinRequest(nick='mesma_pessoa',attempts=3,test_mode=True))
        assert STATE.roleta_active_spin['attempt']==1 and STATE.roleta_active_spin['total_attempts']==3
        for n in (2,3):
            await roleta.mark_finished();await asyncio.sleep(.04)
            assert STATE.roleta_active_spin['nick']=='mesma_pessoa'
            assert STATE.roleta_active_spin['attempt']==n
        await roleta.mark_finished();await asyncio.sleep(.04)
        history=await db.roleta_history_list()
        assert len(history)==3 and all(entry['nick']=='mesma_pessoa' for entry in history)
        assert not STATE.roleta_visible
    run(scenario())


def test_captcha_timeout_marks_expired_and_advances():
    async def scenario():
        from servidor.giveaway import GiveawayEngine
        from servidor.state import add_participant
        engine=GiveawayEngine();await engine.start('!sorteio')
        STATE.antibot_enabled=True;STATE.antibot_random_chance=100
        add_participant('kick','teste')
        await engine.draw()
        STATE.winner_deadline=time.time()+.01
        engine.restart_timer()
        await asyncio.sleep(.15)
        assert STATE.current_winner is None
        assert STATE.participants['kick:teste'].captcha_status=='expired'
        assert STATE.antibot_challenge is None
    run(scenario())


def test_twitch_shared_chat_preserves_origin_and_mentions():
    from servidor.twitch_chat import _parse_notification
    msg=_parse_notification({'broadcaster_user_login':'meucanal','chatter_user_login':'viewer','message_id':'copy',
        'source_broadcaster_user_id':'99','source_broadcaster_user_login':'parceiro','source_message_id':'original',
        'message':{'text':'Olá @meucanal','fragments':[{'type':'mention','mention':{'user_login':'meucanal'}}]}})
    assert msg.source_channel=='parceiro' and msg.channel=='meucanal'
    assert msg.mentions==['meucanal'] and msg.source_message_id=='original'


@pytest.mark.parametrize('platform',['twitch','kick'])
def test_live_chat_records_even_without_giveaway_and_deduplicates(platform):
    async def scenario():
        manager=ChatManager();manager.on_chat_message=AsyncMock()
        cls=TwitchMessage if platform=='twitch' else KickMessage
        message=cls(username='viewer',display_name='Viewer',message='conversa normal',message_id='id')
        await getattr(manager,'_on_'+platform)(message)
        await getattr(manager,'_on_'+platform)(message)
        assert len(STATE.chat_messages)==1 and not STATE.participants
        manager.on_chat_message.assert_awaited_once()
        for n in range(305):
            await manager._record_chat(cls(username='viewer',message=str(n),message_id=str(n)))
        assert len(STATE.chat_messages)==300
    run(scenario())


def test_manual_chat_send_does_not_enable_announcements(monkeypatch):
    async def scenario():
        import importlib
        module=importlib.import_module('servidor.app');STATE.simulation_mode=False
        sender=AsyncMock(return_value=True);monkeypatch.setattr(module.chat,'send',sender)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
            assert (await c.post('/api/chat/send',json={'platform':'twitch','text':'teste'})).status_code==200
            sender.assert_awaited_once_with('twitch','teste',automatic=False)
            assert not STATE.bot_twitch_enabled
            assert (await c.post('/api/chat/send',json={'platform':'outro','text':'teste'})).status_code==422
            assert (await c.post('/api/chat/send',json={'platform':'kick','text':' '*5})).status_code==422
            STATE.simulation_mode=True
            assert (await c.post('/api/chat/send',json={'platform':'kick','text':'teste'})).status_code==400
    run(scenario())


def test_twitch_avatar_token_prefix_and_validation_share_http_client():
    async def scenario():
        from servidor import twitch_api
        STATE.bot_twitch_client_id='client';STATE.bot_twitch_oauth='oauth:abc-token'
        def handler(req):
            if req.url.path.endswith('/validate'):
                assert req.headers['Authorization']=='OAuth abc-token'
                return httpx.Response(200,json={'user_id':'1','client_id':'client','login':'conta','scopes':['user:read:chat','user:write:chat']})
            assert req.headers['Authorization']=='Bearer abc-token'
            return httpx.Response(200,json={'data':[{'profile_image_url':'https://example.com/avatar.png'}]})
        original=httpx.AsyncClient
        with patch('servidor.twitch_api.httpx.AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(handler))):
            token=await twitch_api.validate_token('client','oauth:abc-token')
            assert token.login=='conta' and token.has_write_chat
            twitch_api.clear_cache()
            assert await twitch_api.get_avatar('1')=='https://example.com/avatar.png'
    run(scenario())


def test_twitch_rejects_client_id_from_another_app():
    async def scenario():
        from servidor import twitch_api
        from servidor.twitch_chat import TwitchAuthError
        token=twitch_api.TokenInfo(user_id='1',client_id='other',scopes=['user:read:chat'])
        with patch('servidor.twitch_api.validate_token',AsyncMock(return_value=token)):
            with pytest.raises(TwitchAuthError):
                await TwitchChat()._validate_credentials('client','fake')
    run(scenario())


def test_shared_channel_cannot_control_main_roleta():
    async def scenario():
        manager=ChatManager()
        await manager._on_twitch(TwitchMessage(username='dono_parceiro',message='!roleta',is_broadcaster=True,
            channel='meucanal',source_channel='parceiro',source_broadcaster_id='99'))
        assert not STATE.roleta_visible
        assert STATE.chat_messages[-1]['source_channel']=='parceiro'
    run(scenario())


def test_roleta_save_all_persists_and_rejects_partial_changes():
    async def scenario():
        first = await roleta.add_or_update_item({'name':'A','weight':50,'active':True,'icon':'A'})
        second = await roleta.add_or_update_item({'name':'B','weight':50,'active':True,'icon':'B'})
        payload = {'items':[{'id':first,'name':'Novo A','weight':75},{'id':second,'name':'B','weight':25}],
                   'duration_seconds':2,'extra_spins':0,'auto_hide':False,'result_seconds':3,'announce_chat':False}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
            result = await c.post('/api/roleta/settings',json=payload)
            assert result.status_code == 200, result.text
            assert STATE.roleta_duration_seconds == 2 and STATE.roleta_extra_spins == 0
            assert not STATE.roleta_auto_hide and not STATE.chat_events['prize_won']
            assert (await db.config_get('chat_events'))['prize_won'] is False
            assert [item['weight'] for item in await db.roleta_list()] == [75,25]
            assert not STATE.bot_twitch_enabled and not STATE.bot_kick_enabled
            invalid = {**payload,'extra_spins':-1,'items':[{'id':first,'name':'Não gravar','weight':1}]}
            assert (await c.post('/api/roleta/settings',json=invalid)).status_code == 422
            stale = {**payload,'items':payload['items'][:1],'duration_seconds':10}
            assert (await c.post('/api/roleta/settings',json=stale)).status_code == 409
            assert STATE.roleta_duration_seconds == 2
            assert (await db.roleta_list())[0]['name'] == 'Novo A'
        # Simula falha de persistência após UPDATE dos prêmios: nenhuma parte fica gravada.
        import aiosqlite
        async with aiosqlite.connect(db.DB_PATH) as conn:
            await conn.execute("CREATE TRIGGER fail_settings BEFORE UPDATE ON config BEGIN SELECT RAISE(ABORT, 'test'); END")
            await conn.commit()
        failed = [{**item,'name':'Não gravar'} for item in await db.roleta_list()]
        with pytest.raises(aiosqlite.IntegrityError):
            await db.roleta_save_settings(failed,{'roleta_duration_seconds':'10'})
        assert (await db.roleta_list())[0]['name'] == 'Novo A'
        assert await db.config_get('roleta_duration_seconds') == '2.0'
    run(scenario())


@pytest.mark.parametrize('platform',['twitch','kick'])
def test_roleta_prize_announcements_obey_switch_and_include_nick(platform):
    async def scenario():
        manager=ChatManager();STATE.simulation_mode=False
        target=getattr(manager,platform)
        target.send_message=AsyncMock(return_value={'success':True} if platform=='twitch' else True)
        setattr(STATE,'bot_'+platform+'_enabled',True)
        STATE.chat_events['prize_won']=False
        await manager.announce('prize_won',nome='Pessoa',premio='VIP')
        target.send_message.assert_not_called()
        STATE.chat_events['prize_won']=True
        await manager.announce('prize_won',nome='Pessoa',premio='VIP')
        assert target.send_message.call_count==1
        text=target.send_message.call_args.args[0]
        assert 'Pessoa' in text and 'VIP' in text
    run(scenario())


@pytest.mark.parametrize('stored,expected',[('#FFD400','#79e8a4'),('#ffcc00','#79e8a4'),('#abcdef','#abcdef')])
def test_theme_upgrade_preserves_custom_colors(stored,expected):
    async def scenario():
        from servidor.app import _load_state_from_db
        await db.config_set('appearance',{'primary_color':stored,'wheel_size':650})
        await _load_state_from_db()
        assert STATE.appearance['primary_color']==expected
        assert STATE.appearance['wheel_size']==650
    run(scenario())


def test_equal_slices_changes_only_visual_snapshot():
    async def scenario():
        STATE.roleta_items=[RoletaItem(1,'Comum',90),RoletaItem(2,'Raro',10)]
        STATE.roleta_equal_slices=True
        with patch('servidor.roleta.random.choices',return_value=[(1,STATE.roleta_items[1])]) as pick:
            await api_roleta_spin(RoletaSpinRequest(test_mode=True))
            assert pick.call_args.kwargs['weights']==[90,10]
            assert STATE.roleta_active_spin['equal_slices'] is True
            assert STATE.roleta_active_spin['prize_id']==2
            STATE.roleta_equal_slices=False
            assert STATE.roleta_active_spin['equal_slices'] is True
        await roleta.set_visible(False)
    run(scenario())


@pytest.mark.parametrize('host,has_workaround',[('127.0.0.1',True),('localhost',False)])
def test_kick_loopback_url_preserves_redirect_and_pkce(host,has_workaround):
    from urllib.parse import parse_qs,urlsplit
    from servidor.kick_oauth import KickOAuth
    uri=f'http://{host}:8777/api/oauth/kick/callback'
    oauth=KickOAuth('app-generated-id',uri,'test-secret')
    url=oauth.start_authorization(include_chat=True)
    parts=urlsplit(url);query=parse_qs(parts.query)
    assert parts.netloc=='id.kick.com' and parts.path=='/oauth/authorize'
    assert query['redirect_uri']==[uri]
    assert ('redirect' in query)==has_workaround
    if has_workaround:assert parts.query.index('redirect=') < parts.query.index('redirect_uri=')
    state=oauth._pending_authorizations[query['state'][0]]
    assert query['code_challenge']==[KickOAuth.generate_code_challenge(state.code_verifier)]
    assert query['code_challenge_method']==['S256']
    assert 'chat:write' in query['scope'][0]
    assert 'test-secret' not in url


def test_kick_start_reports_missing_secret_and_invalid_redirect():
    from servidor.kick_oauth import KickOAuth
    with pytest.raises(ValueError,match='Client Secret'):
        KickOAuth('generated-app-id','http://localhost:8777/api/oauth/kick/callback').start_authorization()
    with pytest.raises(ValueError,match='Redirect URI inválida'):
        KickOAuth('generated-app-id','not-a-url','test-secret').start_authorization()


def test_kick_direct_socket_reads_entries_reconnects_and_deduplicates(monkeypatch):
    async def scenario():
        import websockets
        import servidor.kick_chat as module
        manager=ChatManager()
        monkeypatch.setattr(manager.kick,'_fetch_chatroom_id',AsyncMock())
        STATE.is_running=True;STATE.keyword='!sorteio';STATE.entry_open_kick=True
        received=asyncio.Event();pong=asyncio.Event();sessions=[]
        original=manager.kick._on_message
        async def on_message(message):
            await original(message)
            if len(STATE.chat_messages)==2:received.set()
        manager.kick.set_callback(on_message)
        async def serve(socket):
            sessions.append(socket)
            index=len(sessions)
            await socket.send(json.dumps({'event':'pusher:connection_established','data':'{"socket_id":"1.2"}'}))
            subscription=json.loads(await socket.recv())
            assert subscription['data']['channel']=='chatrooms.77.v2'
            await socket.send(json.dumps({'event':'pusher_internal:subscription_succeeded','channel':'chatrooms.77.v2','data':'{}'}))
            message={'id':str(index),'content':'!sorteio','sender':{'id':index,'username':'Viewer'+str(index),
                'identity':{'color':'#123456','badges':[{'type':'subscriber'},{'type':'vip'}]}}}
            packet={'event':'App\\Events\\ChatMessageEvent','channel':'chatrooms.77.v2','data':json.dumps(message)}
            await socket.send(json.dumps({**packet,'channel':'chatrooms.999.v2'}))
            await socket.send(json.dumps(packet));await socket.send(json.dumps(packet))
            if index==1:
                await socket.send(json.dumps({'event':'pusher:ping'}))
                assert json.loads(await socket.recv())['event']=='pusher:pong'
                pong.set();await socket.close()
            else:await socket.wait_closed()
        async with websockets.serve(serve,'127.0.0.1',0) as server:
            monkeypatch.setattr(module,'PUSHER_URL',f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}')
            try:
                success,error=await manager.connect_kick(channel='streamer',simulate=False,mode='direct',chatroom_id=77)
                assert success,error
                await asyncio.wait_for(received.wait(),5)
                await asyncio.wait_for(pong.wait(),1)
                assert manager.kick.connected
                assert len(sessions)==2 and len(STATE.participants)==2
                assert all(p.is_sub and p.is_vip for p in STATE.participants.values())
                assert len(STATE.chat_messages)==2
            finally:await manager.kick.disconnect()
            assert not manager.kick.connected and manager.kick._task is None
    run(scenario())


def test_kick_direct_failure_does_not_fall_back_to_simulation(monkeypatch):
    async def scenario():
        manager=ChatManager()
        monkeypatch.setattr(manager.kick,'_fetch_chatroom_id',AsyncMock(side_effect=ValueError('HTTP 403: informe o ID da sala')))
        success,error=await manager.connect_kick(channel='streamer',simulate=False,mode='direct')
        assert not success and '403' in error
        assert not manager.kick.connected and manager.kick._task is None
        assert not STATE.chat_messages
    run(scenario())


def test_kick_direct_api_needs_no_oauth_and_keeps_sender_authorization(monkeypatch):
    async def scenario():
        import importlib
        app_module=importlib.import_module('servidor.app')
        manager=ChatManager();monkeypatch.setattr(app_module,'chat',manager)
        async def connect(channel,simulate=True,**kwargs):
            assert simulate is False and kwargs['mode']=='direct'
            manager.kick.channel=channel;manager.kick.connected=True
        monkeypatch.setattr(manager.kick,'connect',connect)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            response=await client.post('/api/chat/kick/connect',json={'channel':'streamer','mode':'direct','chatroom_id':77})
            assert response.status_code==200,response.text
            assert response.json()['simulation'] is False
            assert await db.config_get('kick_receive_enabled') is True
            assert await db.config_get('kick_chatroom_id')==77
            assert STATE.simulation_mode is False
            state=(await client.get('/api/state')).json()
            assert state['kick']['receive_connected'] and state['kick']['receive_mode']=='direct'
            assert (await client.post('/api/chat/kick/connect',json={'channel':'x','mode':'bad'})).status_code==422
            assert (await client.post('/api/chat/kick/disconnect')).status_code==200
            assert await db.config_get('kick_receive_enabled') is False
            assert not (await client.get('/api/state')).json()['kick']['receive_connected']
    run(scenario())


def test_kick_separate_sender_posts_to_selected_channel():
    async def scenario():
        oauth=SimpleNamespace(ensure_valid_token=AsyncMock(return_value=(True,'fake-token')),has_chat_write=lambda:True,
                              get_channel_info=lambda:SimpleNamespace(slug='bot_account',broadcaster_user_id='1'))
        requests=[]
        def handler(request):
            requests.append(request)
            if request.method=='GET':
                assert request.url.params['slug']=='streamer'
                return httpx.Response(200,json={'data':[{'slug':'streamer','broadcaster_user_id':42}]})
            assert json.loads(request.content)=={'type':'user','broadcaster_user_id':42,'content':'Vencedor: Pessoa'}
            return httpx.Response(200,json={'data':{'is_sent':True}})
        sender=KickChat();sender.channel='streamer'
        with patch.object(kick_oauth,'get_oauth',return_value=oauth),patch('servidor.kick_chat.httpx.AsyncClient',return_value=httpx.AsyncClient(transport=httpx.MockTransport(handler))):
            assert await sender.send_message('Vencedor: Pessoa')
        assert len(requests)==2
    run(scenario())


def test_kick_ignores_webhook_when_direct_transport_selected():
    STATE.kick_receive_mode='direct';STATE.kick_receive_enabled=True
    assert ChatManager().handle_kick_webhook_event(SimpleNamespace(event_type='chat.message.sent')) is False


@pytest.mark.parametrize('prefix',['','oauth:','OAUTH:','Bearer '])
def test_twitch_token_inspection_normalizes_and_discovers_issuer(prefix):
    async def scenario():
        from servidor import twitch_api
        original=httpx.AsyncClient
        def handler(request):
            assert request.headers['Authorization']=='OAuth secret-access'
            return httpx.Response(200,json={'client_id':'issuer-id','user_id':'42','login':'conta',
                                           'scopes':['user:read:chat','user:write:chat'],'expires_in':1000})
        with patch('servidor.twitch_api.httpx.AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(handler))):
            info=await twitch_api.validate_token('',prefix+'secret-access')
            assert info.client_id=='issuer-id' and info.has_read_chat and info.has_write_chat
        with patch('servidor.twitch_api.validate_token',AsyncMock(return_value=info)):
            async with original(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                result=await client.post('/api/twitch/token/inspect',json={'oauth':prefix+'secret-access'})
                assert result.status_code==200,result.text
                assert result.json()['client_id']=='issuer-id'
                assert 'secret-access' not in result.text
                assert not STATE.bot_twitch_oauth  # Inspeção não salva nem substitui credenciais.
    run(scenario())


@pytest.mark.parametrize('status',[401,503])
def test_twitch_validation_distinguishes_rejection_and_unavailable(status):
    async def scenario():
        from servidor import twitch_api
        original=httpx.AsyncClient
        with patch('servidor.twitch_api.httpx.AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(lambda req:httpx.Response(status,json={})))):
            if status==401:
                assert await twitch_api.validate_token('id','access') is None
            else:
                with pytest.raises(twitch_api.TokenValidationUnavailable,match='HTTP 503'):
                    await twitch_api.validate_token('id','access')
        if status==503:
            with patch('servidor.twitch_api.validate_token',AsyncMock(side_effect=twitch_api.TokenValidationUnavailable('Falha de comunicação'))):
                async with original(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                    response=await client.post('/api/twitch/token/inspect',json={'oauth':'access'})
                    assert response.status_code==503 and 'comunicação' in response.text
    run(scenario())


def test_twitch_legacy_chat_scope_blocks_before_socket():
    async def scenario():
        from servidor.twitch_api import TokenInfo
        from servidor.twitch_chat import ScopeMissingError
        instance=TwitchChat()
        token=TokenInfo(user_id='42',client_id='issuer',scopes=['chat:read','chat:edit'])
        with patch('servidor.twitch_api.validate_token',AsyncMock(return_value=token)):
            with pytest.raises(ScopeMissingError,match='user:read:chat'):
                await instance.connect('streamer',client_id='issuer',token='access')
        assert not instance.connected and not instance._should_run
    run(scenario())


def test_kick_receives_canonical_wire_packet():
    async def scenario():
        client=KickChat();client.chatroom_id=77
        callback=AsyncMock();client.set_callback(callback)
        # Literal JSON no formato do protocolo; o decoder produz uma barra por separador.
        packet=json.loads(r'{"event":"App\\Events\\ChatMessageEvent","channel":"chatrooms.77.v2","data":{"id":"wire-message","content":"!sorteio","sender":{"id":42,"username":"Pessoa","identity":{"badges":[{"type":"subscriber"}]}}}}')
        assert packet['event'].count(chr(92))==2
        await client._handle_packet(packet)
        callback.assert_awaited_once()
        assert callback.call_args.args[0].username=='pessoa'
        assert callback.call_args.args[0].message=='!sorteio'
        assert callback.call_args.args[0].is_sub
    run(scenario())


def test_kick_send_failure_has_actionable_http_reason():
    async def scenario():
        oauth=SimpleNamespace(ensure_valid_token=AsyncMock(return_value=(True,'fake-token')),has_chat_write=lambda:True,
                              get_channel_info=lambda:SimpleNamespace(slug='streamer',broadcaster_user_id='42'))
        client=KickChat();client.channel='streamer'
        transport=httpx.MockTransport(lambda req:httpx.Response(403,json={'message':'Forbidden'}))
        with patch.object(kick_oauth,'get_oauth',return_value=oauth),patch('servidor.kick_chat.httpx.AsyncClient',return_value=httpx.AsyncClient(transport=transport)):
            assert not await client.send_message('Teste')
            assert 'HTTP 403' in client.last_send_error and 'chat:write' in client.last_send_error
    run(scenario())

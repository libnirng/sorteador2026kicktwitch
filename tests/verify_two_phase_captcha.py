"""Teste independente, sem pytest ou banco real: python tests/verify_two_phase_captcha.py"""
import asyncio
import time
import importlib
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.modules.setdefault('aiosqlite', types.ModuleType('aiosqlite'))

from servidor import db, megamu
from servidor.chat_manager import ChatManager
from servidor.giveaway import GiveawayEngine
from servidor.kick_chat import KickMessage
from servidor.state import STATE, AppState, add_participant
from servidor.app import (_winner_chat_state, ChatSettingsRequest, api_bot_settings,
                         AppearanceRequest, api_appearance, AntibotRequest, api_antibot_config)
from pydantic import ValidationError


async def run():
    real_character_info = megamu.character_info
    STATE.__dict__.update(AppState().__dict__)
    for name in ('sorteio_create', 'sorteio_update', 'config_set', 'audit_add', 'winner_insert', 'winner_update'):
        setattr(db, name, AsyncMock(return_value=1))
    engine = GiveawayEngine()
    importlib.import_module('servidor.giveaway').giveaway = engine
    manager = ChatManager()
    manager.announce = AsyncMock(return_value={})
    engine.chat = manager
    STATE.antibot_enabled = True
    STATE.antibot_random_chance = 100
    STATE.captcha_waive_subs_vips = False
    STATE.captcha_send_to_chat = True
    STATE.chat_events['captcha_challenge'] = True
    # Suspense real: clicar em Sortear NÃO dispara anúncio nem desconta o prazo.
    STATE.appearance['draw_animation'] = 'roulette'
    STATE.appearance['draw_animation_seconds'] = .06  # acelera somente o teste
    await engine.start('!entrar')
    add_participant('kick', 'biaabs')
    await engine.draw()
    suspense_winner = STATE.current_winner
    assert STATE.draw_reveal_until > 0 and STATE.winner_deadline == 0
    assert not any(c.args[0] == 'winner_announced' for c in manager.announce.call_args_list)
    await manager._on_kick(KickMessage(username='biaabs', message='resposta antes de revelar'))
    assert STATE.current_winner is suspense_winner and not suspense_winner.presence_confirmed
    assert STATE.antibot_challenge is None
    await asyncio.sleep(.095)
    assert STATE.draw_reveal_until == 0 and STATE.winner_deadline > __import__('time').time()+59
    assert any(c.args[0] == 'winner_announced' for c in manager.announce.call_args_list)
    # Encerramento durante outra animação não revela nem anuncia depois.
    manager.announce.reset_mock()
    await engine.start('!entrar')
    add_participant('kick', 'biaabs')
    await engine.draw()
    assert STATE.draw_reveal_until > 0
    await engine.stop()
    await asyncio.sleep(.09)
    assert STATE.draw_reveal_until == 0 and STATE.winner_deadline == 0
    assert not any(c.args[0] == 'winner_announced' for c in manager.announce.call_args_list)
    # O estilo aleatório é definido pelo servidor, permanece fixo no mesmo
    # vencedor e nunca é igual ao sorteio imediatamente anterior.
    from servidor.giveaway import DRAW_ANIMATIONS
    STATE.appearance['draw_animation'] = 'random'
    styles_seen = []
    for _ in range(16):
        await engine.start('!entrar')
        add_participant('kick', 'biaabs')
        await engine.draw()
        active_style = STATE.draw_animation_active
        assert active_style in DRAW_ANIMATIONS
        assert active_style != (styles_seen[-1] if styles_seen else None)
        styles_seen.append(active_style)
        await engine.stop()
    assert len(styles_seen) == 16
    # Modo sem suspense mantém o comportamento antigo, se escolhido pelo cliente.
    STATE.appearance['draw_animation'] = 'none'
    manager.announce.reset_mock()
    await engine.start('!entrar')
    add_participant('kick', 'biaabs')
    await engine.draw()
    w = STATE.current_winner
    assert w and w.captcha_required and not w.presence_confirmed
    assert STATE.antibot_challenge is None, 'O desafio saiu antes da primeira fala'
    assert STATE.winner_deadline > 0
    assert not any(call.args[0] == 'captcha_challenge' for call in manager.announce.call_args_list)

    await manager._on_kick(KickMessage(username='biaabs', message='as'))
    await asyncio.sleep(0)
    assert w.presence_confirmed and w.answered
    assert STATE.winner_deadline == 0 and engine._timer_task is None
    assert STATE.antibot_challenge and STATE.antibot_challenge['deadline'] == 0
    expected = STATE.antibot_challenge['expected']
    assert any(call.args[0] == 'captcha_challenge' for call in manager.announce.call_args_list)

    await manager._on_kick(KickMessage(username='biaabs', message='resposta definitivamente errada'))
    await asyncio.sleep(0)
    assert STATE.captcha_feedback['status'] == 'wrong'
    assert 'expected' not in STATE.captcha_feedback, 'Não pode revelar solução antes da última tentativa'
    assert STATE.captcha_feedback['attempts'] == 1
    assert STATE.antibot_challenge is not None and STATE.antibot_challenge['attempts'] == 1
    assert STATE.winner_deadline == 0 and not w.captcha_failed
    retry = [c for c in manager.announce.call_args_list if c.args[0] == 'captcha_retry']
    assert len(retry)==1 and retry[0].kwargs['tentativa']==1
    assert not [c for c in manager.announce.call_args_list if c.args[0] == 'captcha_fail']
    STATE.antibot_max_attempts=1  # mudar configuração não encurta desafio já aberto
    await manager._on_kick(KickMessage(username='biaabs', message='resposta definitivamente errada'))
    assert STATE.captcha_feedback['attempts'] == 2 and 'expected' not in STATE.captcha_feedback
    assert STATE.antibot_challenge is not None and not w.captcha_failed
    STATE.antibot_max_attempts=3
    await manager._on_kick(KickMessage(username='biaabs', message='resposta definitivamente errada'))
    assert STATE.captcha_feedback['expected'] == expected
    assert STATE.captcha_feedback['exhausted'] and STATE.captcha_feedback['attempts'] == 3
    assert STATE.winner_deadline == 0 and STATE.antibot_challenge is None
    assert STATE.current_winner is w and w.captcha_failed and not w.delivered
    await asyncio.gather(*manager._announcements)
    fail = [c for c in manager.announce.call_args_list if c.args[0] == 'captcha_fail']
    assert len(fail) == 1 and fail[0].kwargs['resposta'] == expected
    await manager._on_kick(KickMessage(username='biaabs', message=str(expected)))
    assert STATE.current_winner is w and not w.delivered, 'Resposta extra confirmou prêmio incorretamente'

    # Configuração 0: tentativas realmente ilimitadas, sem revelar a solução.
    STATE.antibot_max_attempts=0
    await engine.start('!entrar')
    add_participant('kick','biaabs')
    await engine.draw()
    await manager._on_kick(KickMessage(username='biaabs',message='presente'))
    assert STATE.antibot_challenge['max_attempts']==0
    answer_unlimited=STATE.antibot_challenge['expected']
    for number in range(1,6):
        await manager._on_kick(KickMessage(username='biaabs',message='resposta errada'))
        assert STATE.antibot_challenge and STATE.antibot_challenge['attempts']==number
        assert STATE.captcha_feedback['remaining'] is None
        assert 'expected' not in STATE.captcha_feedback
        assert not STATE.current_winner.captcha_failed
    await manager._on_kick(KickMessage(username='biaabs',message=answer_unlimited))
    assert STATE.current_winner is None and STATE.winner_claim_pending is not None
    await asyncio.gather(*manager._announcements)
    STATE.antibot_max_attempts=3

    await engine.start('!entrar')
    add_participant('kick', 'biaabs')
    await engine.draw()
    await manager._on_kick(KickMessage(username='biaabs', message='presente'))
    sent_order = []
    async def slow_announcement(event, **values):
        if event == 'captcha_success':
            await asyncio.sleep(.02)  # reproduz envio mais demorado na plataforma
        sent_order.append(event)
        return {}
    manager.announce = AsyncMock(side_effect=slow_announcement)
    code = STATE.antibot_challenge['expected']
    await manager._on_kick(KickMessage(username='biaabs', message=code))
    assert STATE.current_winner is None and STATE.winners[-1].captcha_passed
    assert STATE.winners[-1].answered and STATE.winners[-1].delivered
    assert STATE.winner_deadline == 0
    assert STATE.winner_claim_pending is STATE.winners[-1]
    assert _winner_chat_state()['awaiting_nick'], 'OBS deveria aguardar !nick após CAPTCHA correto'
    assert _winner_chat_state()['captcha_confirmed']
    await asyncio.gather(*manager._announcements)
    calls = [c.args[0] for c in manager.announce.call_args_list]
    assert calls.index('captcha_success') < calls.index('winner_claim_instructions'), 'Ordem das mensagens invertida'
    assert sent_order.index('captcha_success') < sent_order.index('winner_claim_instructions'), 'Envio saiu fora de ordem'
    claims = [c for c in manager.announce.call_args_list if c.args[0] == 'winner_claim_instructions']
    assert len(claims) == 1 and claims[0].kwargs['nome'] == 'biaabs'

    # Enquanto !nick não for validado, continua no OBS. Só o próprio vencedor
    # e a mesma plataforma podem concluir a retirada.
    megamu.character_info = AsyncMock(return_value='✅ Personagem encontrado')
    await manager._on_kick(KickMessage(username='outro_user', message='!nick Outro'))
    await asyncio.gather(*manager._announcements)
    assert STATE.winner_claim_pending is not None
    megamu.character_info = AsyncMock(side_effect=ValueError('Personagem inexistente'))
    await manager._on_kick(KickMessage(username='biaabs', message='!NaoExiste'))
    await asyncio.gather(*manager._announcements)
    assert STATE.winner_claim_pending is not None, 'Nick inválido encerrou a espera no OBS'
    assert megamu.character_info.call_args.args[0]=='NaoExiste', 'Formato !NomeDoPersonagem ignorado'
    assert _winner_chat_state()['nick_verification']['status']=='error'
    assert 'inexistente' in _winner_chat_state()['nick_verification']['result']
    await manager._on_kick(KickMessage(username='biaabs', message='!OutroNick'))
    assert _winner_chat_state()['nick_verification']['status']=='waiting', 'Cooldown silenciou tentativa sem feedback'
    manager._nick_request_at.pop(('kick', 'biaabs'), None)  # permite repetir no teste sem esperar 2 s
    megamu.character_info = AsyncMock(return_value='✅ Personagem encontrado')
    await manager._on_kick(KickMessage(username='biaabs', message='!MeuPersonagem'))
    await asyncio.gather(*manager._announcements)
    assert STATE.winner_claim_pending is None
    assert _winner_chat_state()['nick_verification']['status']=='success'
    assert _winner_chat_state()['nick_verification']['nick']=='MeuPersonagem'
    assert 'encontrado' in _winner_chat_state()['nick_verification']['result']
    assert _winner_chat_state()['nick_verification']['chat_sent'] is False
    STATE.winner_claim_feedback_until=time.time()-1
    assert _winner_chat_state() is None, 'Prêmio confirmado ficou permanentemente no OBS'
    assert megamu.character_info.call_count == 1
    assert any(c.args[1] == 'winner_claim_nick' for c in db.audit_add.call_args_list)

    # Verifica a requisição GET e os dois formatos de resposta da página
    # MEGAMU sem consultar uma conta real nem depender da rede.
    response=types.SimpleNamespace(status_code=200,
        text='[Darcherman] 400 (120 rr), HuntLevel: 33')
    client=AsyncMock()
    client.get=AsyncMock(return_value=response)
    with patch.object(megamu.httpx,'AsyncClient') as client_cls:
        client_cls.return_value.__aenter__.return_value=client
        info=await real_character_info('Darcherman')
    assert 'Darcherman' in info and '120 RR' in info and 'Hunt 33' in info
    assert client.get.call_args.args[0]=='https://megamu.net/getdata.php'
    assert client.get.call_args.kwargs['params']['char']=='Darcherman'
    response.text='Player não existente.'
    with patch.object(megamu.httpx,'AsyncClient') as client_cls:
        client_cls.return_value.__aenter__.return_value=client
        try:
            await real_character_info('Darcherman')
        except ValueError as error:
            assert 'não existe' in str(error)
        else:
            raise AssertionError('O MEGAMU retornou personagem inexistente como válido')

    # Sem captcha, a primeira mensagem já confirma e dispara a instrução.
    await engine.start('!entrar')
    STATE.antibot_enabled = False
    STATE.nick_lookup_command = '!personagem'
    add_participant('kick', 'biaabs')
    await engine.draw()
    assert _winner_chat_state() is not None
    manager.announce.reset_mock()
    await manager._on_kick(KickMessage(username='biaabs', message='oi'))
    await asyncio.gather(*manager._announcements)
    assert STATE.current_winner is None and STATE.winner_deadline == 0
    assert _winner_chat_state()['awaiting_nick']
    claims = [c for c in manager.announce.call_args_list if c.args[0] == 'winner_claim_instructions']
    assert len(claims) == 1

    # Quando o prazo expira sem resposta, nenhum cartão de chat deve sobrar.
    await engine.start('!entrar')
    STATE.winner_timer_seconds = .03
    add_participant('kick', 'sem_resposta')
    await engine.draw()
    await asyncio.sleep(.08)
    assert STATE.current_winner is None and STATE.winner_claim_pending is None
    assert _winner_chat_state() is None
    # Mensagens personalizadas de versões anteriores não tinham {resposta}.
    # Mesmo com esse texto antigo, o bot deve revelar a solução após o erro.
    STATE.simulation_mode = False
    STATE.bot_kick_enabled = True
    STATE.message_templates['captcha_fail']['kick'] = '❌ Resposta incorreta, {nome}.'
    manager.announce = ChatManager.announce.__get__(manager, ChatManager)
    manager.send = AsyncMock(return_value=True)
    await manager.announce('captcha_fail', platform='kick', nome='biaabs', resposta='CJFT')
    sent = manager.send.call_args.args[1]
    assert 'CJFT' in sent and 'resposta correta era' in sent
    await manager.announce('captcha_retry',platform='kick',nome='biaabs',tentativa=1,limite=3,restantes=2)
    assert '1/3' in manager.send.call_args.args[1]
    assert 'CJFT' not in manager.send.call_args.args[1]
    await manager.announce('winner_claim_instructions',platform='kick',nome='biaabs',premio='Teste')
    sent = manager.send.call_args.args[1]
    assert '!personagem NomeDoPersonagem' in sent and 'Teste' in sent
    # A própria tela envia os textos de TODOS os eventos ao salvar; o novo
    # marcador precisa passar pela validação HTTP sem erro 400.
    with patch('servidor.app._sync_connection_env'), patch('servidor.app._notify_state', new=AsyncMock()):
        saved = await api_bot_settings(ChatSettingsRequest(
            kick_enabled=True, events={'winner_claim_instructions': True,'captcha_retry':True},
            templates={'winner_claim_instructions': {
                'kick': '🎁 @{nome}, use {comando_nick} para receber {premio}.'},
                'captcha_retry':{'kick':'❌ {nome}: tentativa {tentativa}/{limite}; restam {restantes}.'}},
            destinations={'winner_claim_instructions': {'kick': True}}))
    assert saved['ok']
    assert STATE.message_templates['winner_claim_instructions']['kick'].endswith('{premio}.')
    assert '{restantes}' in STATE.message_templates['captcha_retry']['kick']
    # Todas as opções de animação devem ser aceitas e persistidas, mas uma
    # string arbitrária não pode virar CSS/classe do OBS.
    for variant in ('classic', 'spotlight', 'rise', 'flip', 'burst', 'random'):
        with patch('servidor.app._notify_state', new=AsyncMock()):
            result = await api_appearance(AppearanceRequest(winner_animation=variant))
        assert result['ok'] and STATE.appearance['winner_animation'] == variant
    for variant in ('roulette', 'slots', 'countdown', 'cards', 'dice',
                    'radar', 'chest', 'particles', 'portal', 'spotlights', 'random', 'none'):
        with patch('servidor.app._notify_state', new=AsyncMock()):
            result = await api_appearance(AppearanceRequest(draw_animation=variant,
                draw_animation_seconds=6))
        assert result['ok'] and STATE.appearance['draw_animation'] == variant
        assert STATE.appearance['draw_animation_seconds'] == 6
    try:
        AppearanceRequest(winner_animation='injetar-classe')
    except ValidationError:
        pass
    else:
        raise AssertionError('API aceitou animação não autorizada')
    for bad in ('injetar-classe', '../x'):
        try:
            AppearanceRequest(draw_animation=bad)
        except ValidationError:
            pass
        else:
            raise AssertionError('API aceitou cena de suspense não autorizada')
    # O operador escolhe 0..100 tentativas e a configuração permanece no banco.
    for allowed in (0,1,3,100):
        with patch('servidor.app._notify_state',new=AsyncMock()):
            saved=await api_antibot_config(AntibotRequest(max_attempts=allowed))
        assert saved['ok'] and STATE.antibot_max_attempts==allowed
        persisted=[c for c in db.config_set.call_args_list
            if c.args[0]=='antibot'][-1].args[1]
        assert persisted['max_attempts']==allowed
    for invalid in (-1,101):
        try:
            AntibotRequest(max_attempts=invalid)
        except ValidationError:
            pass
        else:
            raise AssertionError('API aceitou limite inválido de tentativas')
    await manager.shutdown()
    print('Sorteador: 3 tentativas, 0 ilimitadas, consulta de nick e suspense OBS: OK')


if __name__ == '__main__':
    asyncio.run(run())

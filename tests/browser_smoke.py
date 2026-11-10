import asyncio,json
from pathlib import Path
from playwright.async_api import async_playwright

async def main():
 import httpx
 for _ in range(100):
  try:
   async with httpx.AsyncClient() as c: await c.get('http://127.0.0.1:18777/api/state')
   break
  except Exception: await asyncio.sleep(.1)
 async with async_playwright() as p:
  browser=await p.chromium.launch(headless=True,args=['--no-sandbox'])
  page=await browser.new_page(viewport={'width':1672,'height':1000},device_scale_factor=1)
  errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
  await page.goto('http://127.0.0.1:18777/admin');await page.wait_for_timeout(1000)
  for tab in ['giveaway','participants','roleta','antibot','chats','connections','messages','history','audit','appearance','obs']:
   await page.locator(f'.tab[data-tab="{tab}"]').click();await page.wait_for_timeout(100)
  await page.locator('.tab[data-tab="appearance"]').click()
  await page.locator('#ap-wheel_size').fill('700');await page.locator('#btn-appearance-save').click();await page.wait_for_timeout(400)
  assert await page.locator('#appearance-status').inner_text()=='Configurações salvas.'

  await page.locator('.tab[data-tab="roleta"]').click()
  assert await page.locator('#btn-roleta-save-config').count()==0
  assert await page.locator('#btn-roleta-save-all').is_visible()
  assert await page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--primary').trim()")=='#79e8a4'
  await page.locator('#roleta-announce-chat').uncheck()
  await page.locator('label.switch:has(#roleta-equal-slices)').click()
  await page.locator('#roleta-spins').fill('0');await page.locator('#roleta-duration').fill('0.5');await page.locator('#roleta-result-seconds').fill('1');await page.locator('#btn-roleta-save-all').click()
  await page.wait_for_timeout(250)
  state=await (await page.request.get('http://127.0.0.1:18777/api/state')).json()
  assert state['roleta']['extra_spins']==0
  assert state['chat_events']['prize_won'] is False
  await page.reload();await page.wait_for_timeout(700)
  await page.locator('.tab[data-tab="roleta"]').click()
  assert not await page.locator('#roleta-announce-chat').is_checked()
  assert await page.locator('#roleta-equal-slices').is_checked()
  prizes=[('Gift card','🎁',20),('Skin rara','⚔',10),('VIP','♛',20),('Surpresa','📦',10),('100 pontos','🪙',20),('Bônus','★',20)]
  for name,icon,weight in prizes:
   response=await page.request.post('http://127.0.0.1:18777/api/roleta/items',data={'name':name,'icon':icon,'weight':weight,'active':True});assert response.ok
  items=await (await page.request.get('http://127.0.0.1:18777/api/roleta/items')).json()
  if isinstance(items,dict): items=items['items']
  for item in items: item['weight']=100/len(items)
  await page.request.post('http://127.0.0.1:18777/api/roleta/items/bulk',data={'items':items})
  overlay=await browser.new_page(viewport={'width':1920,'height':1080})
  overlay.on('pageerror',lambda error:errors.append(str(error)))
  await overlay.add_init_script('''window.__arcs=[];const originalArc=CanvasRenderingContext2D.prototype.arc;CanvasRenderingContext2D.prototype.arc=function(x,y,r,start,end,...rest){if(r===532 && end-start>0 && end-start<Math.PI*2-0.001){window.__arcs.push([start,end]);if(window.__arcs.length>100)window.__arcs.shift();}return originalArc.call(this,x,y,r,start,end,...rest)};''')
  await overlay.goto('http://127.0.0.1:18777/overlay/roleta');await overlay.wait_for_timeout(500)
  assert not await overlay.locator('#stage').is_visible()
  # actual UI 2 attempt sequence
  await page.locator('#roleta-nick').fill('darcherman');await page.locator('#roleta-attempts').fill('2')
  # Um campo inválido não pode iniciar giro nem salvar parcialmente.
  await page.locator('.roleta-item .ri-name').first.fill('')
  await page.locator('#btn-roleta-spin').click()
  await page.wait_for_timeout(250)
  assert 'Confira os campos' in await page.locator('#roleta-status').inner_text()
  before=await (await page.request.get('http://127.0.0.1:18777/api/state')).json()
  assert not before['roleta']['spinning']
  # Girar salva os rascunhos e inicia a animação sem Mostrar overlay.
  await page.locator('.roleta-item .ri-name').first.fill('Gift card atualizado')
  await page.locator('.roleta-item .ri-weight').first.fill('60')
  await page.locator('#roleta-duration').fill('0.6')
  async with page.expect_response('**/api/roleta/spin') as spinning:
   await page.locator('#btn-roleta-spin').click()
  assert (await spinning.value).ok
  after=await (await page.request.get('http://127.0.0.1:18777/api/state')).json()
  assert after['roleta']['duration_seconds']==0.6
  assert any(i['name']=='Gift card atualizado' and i['weight']==60 for i in after['roleta']['items'])
  await overlay.wait_for_selector('#stage.visible');await overlay.wait_for_timeout(150)
  assert await overlay.evaluate("getComputedStyle(document.body).backgroundColor")=='rgba(0, 0, 0, 0)'

  await overlay.wait_for_timeout(650)
  geometry=await overlay.evaluate('window.__arcs.slice(-6)')
  import math
  assert len(geometry)==6
  assert all(abs(end-start-math.pi/3)<0.001 for start,end in geometry),geometry
  shown=await (await page.request.get('http://127.0.0.1:18777/api/state')).json()
  snap=shown['roleta']['active_spin']
  active=[i for i in snap['items'] if i['active']]
  chosen=next(i for i,item in enumerate(active) if item['id']==snap['prize_id'])
  start,end=geometry[chosen]
  assert ((-math.pi/2-start)%(math.pi*2)) <= end-start+0.001
  await overlay.wait_for_timeout(5000)
  state=await (await page.request.get('http://127.0.0.1:18777/api/state')).json()
  assert not state['roleta']['visible'] and not state['roleta']['spinning'] and state['roleta']['remaining']==0,state['roleta']
  assert not await overlay.locator('#stage').is_visible()
  history=await (await page.request.get('http://127.0.0.1:18777/api/roleta/history')).json()
  print('history',len(history if isinstance(history,list) else history.get('history',[])))
  # Valores digitados devem continuar iguais ao recarregar o painel.
  await page.reload();await page.wait_for_timeout(700)
  await page.locator('.tab[data-tab="roleta"]').click()
  assert await page.locator('.roleta-item .ri-weight').first.input_value()=='60'
  # appearance reload persistence, chat save without transmission
  await page.locator('.tab[data-tab="appearance"]').click();assert await page.locator('#ap-wheel_size').input_value()=='700'
  await page.locator('.tab[data-tab="chats"]').click()
  assert await page.locator('#chat-mention-names').is_visible()
  assert not await page.locator('#twitch-client-id').is_visible()
  await page.locator('#btn-open-connections').click()
  assert await page.locator('#bc-title').inner_text()=='Conexões'
  assert await page.locator('#twitch-client-id').is_visible()
  assert await page.locator('#kick-client-id').is_visible()
  assert not await page.locator('#twitch-chat-feed').is_visible()
  assert await page.locator('#twitch-client-id').count()==1
  megamu_requests=[]
  async def mock_megamu_config(route):
   megamu_requests.append(route.request.post_data_json)
   await route.fulfill(status=200,content_type='application/json',body='{"ok":true}')
  await page.route('**/api/megamu/config',mock_megamu_config)
  await page.locator('#megamu-dv').fill('test-dv')
  await page.locator('#megamu-key').fill('test-private-key')
  await page.locator('#megamu-enabled').check()
  await page.locator('#btn-megamu-save').click()
  await page.wait_for_timeout(200)
  assert megamu_requests==[{'dv':'test-dv','key':'test-private-key','enabled':True}]
  assert await page.locator('#megamu-key').input_value()==''
  async def mock_megamu_awards(route):
   await page.request.post("http://127.0.0.1:18777/api/_test/awards",data={"names":["Condor Flame"]})
   await route.fulfill(status=200,content_type='application/json',body=json.dumps({'dv':'test-dv','has_key':True,'enabled':True,'awards':[{'name':'Condor Flame'}],'error':'','updated_at':1}))
  await page.route('**/api/megamu/awards',mock_megamu_awards)
  await page.locator('#btn-megamu-test').click()
  await page.wait_for_timeout(200)
  assert 'Condor Flame' in await page.locator('#megamu-awards').inner_text()
  assert '1 prêmios' in await page.locator('#megamu-feedback').inner_text()
  await page.unroute('**/api/megamu/config',mock_megamu_config)
  await page.unroute('**/api/megamu/awards',mock_megamu_awards)
  await page.locator('.tab[data-tab="messages"]').click()
  assert not await page.locator('#twitch-client-id').is_visible()
  await page.locator('#event-entry_accepted').locator('xpath=ancestor::details').locator('summary').click()
  await page.locator('#tpl-entry_accepted-twitch').fill('Oi {nome}! Chance atual: {chance}%')
  await page.locator('#dest-entry_accepted-kick').uncheck()
  await page.locator('#btn-chat-settings-save').click();await page.wait_for_timeout(250)
  assert await page.locator('#chat-settings-status').inner_text()=='Configurações salvas.'
  await page.reload();await page.wait_for_timeout(800)
  await page.locator('.tab[data-tab="messages"]').click()
  assert await page.locator('#tpl-entry_accepted-twitch').input_value()=='Oi {nome}! Chance atual: {chance}%'
  assert not await page.locator('#dest-entry_accepted-kick').is_checked()
  if __import__('os').environ.get('SORTEADOR_QA_SCREENSHOTS'):
   await page.screenshot(path=__import__('os').environ['SORTEADOR_QA_SCREENSHOTS']+'/messages.png',full_page=True)
  await page.locator('.tab[data-tab="giveaway"]').click();await page.evaluate('window.scrollTo(0,0)');await page.wait_for_timeout(400)
  await page.locator('.tab[data-tab="giveaway"]').click()
  assert await page.locator('.tab[data-tab="messages"] svg').count()==1
  assert await page.locator('#giveaway-award').count()==0
  assert await page.locator('#btn-giveaway-next').count()==0
  assert await page.locator('#btn-megamu-import').count()==0
  await page.locator('.giveaway-weight-settings summary').click()
  for platform,sub,vip in [('twitch','1,5','2.5'),('kick','2,5','1.5')]:
   await page.locator('#weight-'+platform+'-sub').fill(sub)
   await page.locator('#weight-'+platform+'-vip').fill(vip)
  await page.locator('#btn-giveaway-weights-save').click()
  await page.wait_for_timeout(250)
  data=await (await page.request.get('http://127.0.0.1:18777/api/state')).json()
  assert data['permissions']['multipliers']['twitch']['sub']==.5
  assert data['permissions']['multipliers']['kick']['sub']==1.5
  await page.locator('.giveaway-weight-settings summary').click()
  await page.request.post('http://127.0.0.1:18777/api/_test/awards',data={'names':['MegaMu '+str(n) for n in range(15)]})
  await page.locator('#btn-giveaway-prize-add').click()
  await page.locator('#giveaway-prize-name').fill('Gift card de R$ 50')
  await page.locator('#giveaway-prize-form button[type="submit"]').click()
  await page.wait_for_timeout(250)
  assert await page.locator('.giveaway-prize-remove').count()==1
  assert await page.locator('.giveaway-prize-select').count()==16
  assert await page.locator('#giveaway-prize-list').evaluate('el=>el.scrollHeight>el.clientHeight && el.clientHeight<=260')
  await page.locator('.giveaway-prize-select').filter(has_text='Gift card de R$ 50').click()
  await page.wait_for_timeout(250)
  assert 'Gift card de R$ 50' in await page.locator('#giveaway-selected-prize').inner_text()
  await page.locator('#giveaway-keyword').fill('!sorteio')
  await page.locator('#giveaway-timer').fill('75')
  giveaway_overlay=await browser.new_page(viewport={'width':1920,'height':1080})
  async def avatar_image(route):
   await route.fulfill(status=200,content_type='image/svg+xml',body='<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="green"/></svg>')
  await giveaway_overlay.route('https://avatar.example.test/official.png',avatar_image)
  fallback_overlay=await browser.new_page(viewport={'width':1920,'height':1080})
  await fallback_overlay.add_init_script('window.WebSocket=class {close(){}}')
  await fallback_overlay.goto('http://127.0.0.1:18777/overlay/sorteio')
  giveaway_overlay.on('pageerror',lambda error:errors.append(str(error)))
  await giveaway_overlay.goto('http://127.0.0.1:18777/overlay/sorteio')
  await giveaway_overlay.wait_for_function("getComputedStyle(document.body).visibility === 'hidden'")
  async with page.expect_response('**/api/giveaway/start') as pending:
   await page.locator('#btn-giveaway-start').click()
  assert (await pending.value).ok
  await giveaway_overlay.wait_for_function("getComputedStyle(document.body).visibility === 'visible'")
  await giveaway_overlay.wait_for_selector('#prizes .prize-name:has-text("Gift card de R$ 50")')
  assert await giveaway_overlay.locator('#prizes button').count()==0
  assert 'Personalizado' not in await giveaway_overlay.locator('#prizes').inner_text()
  assert 'MegaMu 0' in await giveaway_overlay.locator('#prizes').inner_text()
  assert await page.locator('#giveaway-twitch-light').evaluate("el=>getComputedStyle(el).backgroundColor")=='rgb(69, 169, 255)'
  assert await page.locator('#giveaway-kick-light').evaluate("el=>getComputedStyle(el).backgroundColor")=='rgb(109, 226, 143)'
  if __import__('os').environ.get('SORTEADOR_QA_SCREENSHOTS'):
   await page.evaluate('window.scrollTo(0,0)')
   await page.screenshot(path=__import__('os').environ['SORTEADOR_QA_SCREENSHOTS']+'/giveaway-prizes.png',full_page=True)
  await fallback_overlay.wait_for_function("getComputedStyle(document.body).visibility === 'visible'")
  await giveaway_overlay.reload()
  await giveaway_overlay.wait_for_function("getComputedStyle(document.body).visibility === 'visible'")
  assert 'simulação' in await page.locator('#giveaway-announcement-result').inner_text()
  await page.request.post('http://127.0.0.1:18777/api/_debug/inject',data={'platform':'twitch','username':'participante_teste'})
  await page.request.post('http://127.0.0.1:18777/api/_test/chat',data={'id':'avatar-before-draw','platform':'twitch','username':'participante_teste','text':'olá','avatar_url':'https://avatar.example.test/official.png'})
  await giveaway_overlay.wait_for_function("document.querySelector('.p-avatar img')?.naturalWidth > 0")
  await page.wait_for_timeout(300)
  await page.locator('#btn-giveaway-pause').click()
  await page.wait_for_timeout(200)
  await page.locator('#btn-giveaway-draw').click()
  await page.wait_for_selector('#giveaway-current-winner-alt.show')
  await giveaway_overlay.evaluate("window.__stableCard=document.querySelector('.p-card');window.__stablePrize=document.querySelector('.prize-item');window.__stableWinner=document.querySelector('#w-avatar img');")
  await giveaway_overlay.wait_for_timeout(2400)
  assert await giveaway_overlay.evaluate("window.__stableCard===document.querySelector('.p-card') && window.__stablePrize===document.querySelector('.prize-item') && window.__stableWinner===document.querySelector('#w-avatar img')")
  assert 'participante_teste' in await page.locator('#giveaway-current-winner-alt').inner_text()
  assert 'Gift card de R$ 50' in await page.locator('#giveaway-current-winner-alt').inner_text()
  await giveaway_overlay.wait_for_function("document.querySelector('#w-avatar img')?.naturalWidth > 0")
  assert not await page.locator('#giveaway-no-winner').is_visible()
  data=await (await page.request.get('http://127.0.0.1:18777/api/state')).json()
  assert data['giveaway']['is_paused'] and data['giveaway']['timer']==75
  assert not await page.locator('#giveaway-auto-advance').is_checked()
  await page.locator('label.switch:has(#giveaway-auto-advance)').click()
  await page.wait_for_timeout(200)
  data=await (await page.request.get('http://127.0.0.1:18777/api/state')).json()
  assert data['giveaway']['auto_advance_timeout']
  await page.locator('label.switch:has(#giveaway-auto-advance)').click()
  assert await page.locator('#btn-giveaway-answer').count()==0
  await page.request.post('http://127.0.0.1:18777/api/_test/chat',data={'id':'confirm-auto','platform':'twitch','username':'participante_teste','text':'estou aqui'})
  await page.wait_for_timeout(300)
  assert await page.locator('#giveaway-no-winner').is_visible()
  assert not await page.locator('#giveaway-timer-display').is_visible()
  await page.request.post('http://127.0.0.1:18777/api/_test/awards',data={'names':[]})
  await page.wait_for_timeout(200)
  assert await page.locator('.giveaway-prize-select').count()==1
  assert 'Gift card de R$ 50' in await giveaway_overlay.locator('#prizes').inner_text()
  # Novo sorteio para conferir o encerramento com vencedor ativo.
  await page.request.post('http://127.0.0.1:18777/api/giveaway/start',data={'keyword':'!sorteio'})
  await page.request.post('http://127.0.0.1:18777/api/_debug/inject',data={'platform':'twitch','username':'participante_teste'})
  await page.request.post('http://127.0.0.1:18777/api/giveaway/draw',data={})
  # Encerrar oculta o OBS mesmo mantendo o vencedor no histórico/estado.
  stopped=await page.request.post('http://127.0.0.1:18777/api/giveaway/stop')
  assert stopped.ok
  await giveaway_overlay.wait_for_function("getComputedStyle(document.body).visibility === 'hidden'")
  await fallback_overlay.wait_for_function("getComputedStyle(document.body).visibility === 'hidden'")
  closed=await (await page.request.get('http://127.0.0.1:18777/api/state')).json()
  assert closed['giveaway']['current_winner']['username']=='participante_teste'
  # Conversas ao vivo, filtros da colab e menções (som com sintetizador simulado).
  await page.locator('.tab[data-tab="chats"]').click()
  await page.evaluate("""() => {
    window.__soundCount=0;
    window.AudioContext=class {
      constructor(){this.state='running';this.currentTime=0;this.destination={};}
      async resume(){this.state='running';}
      createOscillator(){return {frequency:{value:0},connect(){},disconnect(){},start(){window.__soundCount++;},stop(){}};}
      createGain(){return {gain:{setValueAtTime(){},linearRampToValueAtTime(){}},connect(){},disconnect(){}};}
    };
  }""")
  async def live(id,text,source='meucanal',platform='twitch'):
   r=await page.request.post('http://127.0.0.1:18777/api/_test/chat',data={'platform':platform,'channel':'meucanal','source_channel':source,'id':id,'text':text})
   assert r.ok
   await page.wait_for_timeout(100)
  await live('own1','Mensagem do meu canal')
  assert 'Mensagem do meu canal' in await page.locator('#twitch-chat-feed').inner_text()
  await page.locator('#twitch-sound-test').click()
  await page.locator('#twitch-chat-sound').check()
  await live('guest1','Mensagem da colab','parceiro')
  assert 'Mensagem da colab' not in await page.locator('#twitch-chat-feed').inner_text()
  await page.wait_for_timeout(400)
  await live('guestmention','Olá @meucanal','parceiro')
  assert 'Olá @meucanal' in await page.locator('#twitch-chat-feed').inner_text()
  assert await page.locator('#twitch-chat-feed .mention').count()==1
  assert await page.evaluate('window.__soundCount')==2
  await page.evaluate('render()')
  assert await page.evaluate('window.__soundCount')==2
  await page.locator('#twitch-chat-scope').select_option('all')
  assert 'Mensagem da colab' in await page.locator('#twitch-chat-feed').inner_text()
  await page.locator('#twitch-channels-button').click()
  await page.locator('#twitch-channel-options input[value="meucanal"]').uncheck()
  assert await page.locator('#twitch-chat-scope').input_value()=='selected'
  assert 'Mensagem do meu canal' not in await page.locator('#twitch-chat-feed').inner_text()
  await page.locator('#twitch-sound-mode').select_option('mentions')
  await live('xss','<img src=x onerror="window.bad=true">','parceiro')
  assert await page.locator('#twitch-chat-feed img').count()==0
  assert await page.evaluate('window.__soundCount')==2
  await live('kick1','Conversa da Kick',platform='kick')
  assert 'Conversa da Kick' in await page.locator('#kick-chat-feed').inner_text()
  await page.locator('#twitch-only-mentions').check()
  assert 'Mensagem da colab' not in await page.locator('#twitch-chat-feed').inner_text()
  await page.reload();await page.wait_for_timeout(700)
  await page.locator('.tab[data-tab="chats"]').click()
  assert await page.locator('#twitch-chat-scope').input_value()=='selected'
  assert await page.locator('#twitch-only-mentions').is_checked()
  assert await page.locator('#twitch-helix-token').count()==1
  assert await page.locator('#kick-client-secret').count()==1
  await page.route('**/api/chat/send',lambda route:route.fulfill(status=200,content_type='application/json',body='{"ok":true}'))
  await page.evaluate("state.connections.simulation_mode=false;state.connections.twitch.connected=true;renderLiveChats()")
  await page.locator('#twitch-chat-message').fill('Mensagem de teste local')
  await page.locator('#twitch-chat-send').click()
  await page.wait_for_timeout(200)
  assert 'Mensagem enviada' in await page.locator('#twitch-chat-feedback').inner_text()
  await page.evaluate('state.connections.simulation_mode=true')
  import os
  if os.environ.get('SORTEADOR_QA_SCREENSHOTS'):
   await page.evaluate('window.scrollTo(0,0)')
   await page.screenshot(path=os.environ['SORTEADOR_QA_SCREENSHOTS']+'/chats.png',full_page=True)
   await page.locator('.tab[data-tab="connections"]').click()
   await page.screenshot(path=os.environ['SORTEADOR_QA_SCREENSHOTS']+'/connections.png',full_page=True)
  await page.locator('.tab[data-tab="connections"]').click()
  assert 'não seu nick' in await page.locator('#kick-client-id').locator('..').locator('xpath=following-sibling::p[1]').inner_text()
  assert 'localhost:' in await page.locator('#kick-redirect-uri').input_value()
  await page.locator('#kick-client-id').fill('test-generated-app-id')
  await page.locator('#kick-client-secret').fill('fake-test-secret')
  await page.evaluate('window.__originalOpen=window.open;window.open=()=>null')
  await page.locator('#btn-kick-authorize').click()
  assert 'pop-ups' in await page.locator('#kick-oauth-feedback').inner_text()
  await page.route('**/api/oauth/kick/config',lambda route:route.fulfill(status=200,content_type='application/json',body='{"ok":true}'))
  await page.route('**/api/oauth/kick/start',lambda route:route.fulfill(status=200,content_type='application/json',body='{"authorization_url":"https://id.kick.com/oauth/authorize?test=1"}'))
  await page.evaluate('window.open=()=>({document:{body:{}},location:{replace:(url)=>{window.__kickOpened=url}},close:()=>{}})')
  await page.locator('#btn-kick-authorize').click()
  await page.wait_for_timeout(250)
  assert await page.evaluate('window.__kickOpened')=='https://id.kick.com/oauth/authorize?test=1'
  assert 'Conclua a autorização' in await page.locator('#kick-oauth-feedback').inner_text()
  await page.evaluate('window.open=window.__originalOpen')
  # Recepção direta é independente de OAuth e das configurações do túnel.
  await page.locator('.tab[data-tab="connections"]').click()
  assert await page.locator('#kick-receive-mode').input_value()=='direct'
  assert not await page.locator('#kick-webhook-settings').is_visible()
  await page.locator('#kick-receive-mode').select_option('webhook')
  assert await page.locator('#kick-webhook-settings').is_visible()
  await page.locator('#kick-receive-mode').select_option('direct')
  await page.locator('#kick-receive-channel').fill('streamer')
  async def direct_connect(route):
   data=route.request.post_data_json
   assert data['channel']=='streamer' and data['mode']=='direct' and data['simulation'] is False
   if not data['chatroom_id']:
    await route.fulfill(status=400,content_type='application/json',body='{"detail":"HTTP 403: informe o ID da sala"}')
   else:
    assert data['chatroom_id']==77
    await route.fulfill(status=200,content_type='application/json',body='{"ok":true,"channel":"streamer","mode":"direct"}')
  await page.route('**/api/chat/kick/connect',direct_connect)
  await page.route('https://kick.com/api/v1/channels/streamer',lambda route:route.fulfill(status=403,headers={'Access-Control-Allow-Origin':'*'},content_type='application/json',body='{}'))
  await page.locator('#btn-kick-receive-connect').click()
  await page.wait_for_timeout(100)
  assert '403' in await page.locator('#kick-receive-feedback').inner_text()
  await page.locator('#kick-receive-room').locator('xpath=ancestor::details').locator('summary').click()
  await page.locator('#kick-receive-room').fill('77')
  await page.locator('#btn-kick-receive-connect').click()
  await page.wait_for_timeout(150)
  assert 'sem ngrok' in await page.locator('#kick-receive-feedback').inner_text()
  await page.locator('#kick-receive-room').fill('')
  await page.route('https://kick.com/api/v1/channels/streamer',lambda route:route.fulfill(status=200,headers={'Access-Control-Allow-Origin':'*'},content_type='application/json',body='{"chatroom":{"id":77}}'))
  await page.locator('#btn-kick-receive-connect').click()
  await page.wait_for_timeout(200)
  assert await page.locator('#kick-receive-room').input_value()=='77'
  assert 'sem ngrok' in await page.locator('#kick-receive-feedback').inner_text()
  await page.route('**/api/twitch/token/inspect',lambda route:route.fulfill(status=200,content_type='application/json',body='{"client_id":"issuer-client","login":"conta","has_read_chat":true,"has_write_chat":true}'))
  await page.locator('#twitch-helix-token').fill('fake-access-token')
  await page.locator('#btn-twitch-token-inspect').click()
  await page.wait_for_timeout(150)
  assert await page.locator('#twitch-client-id').input_value()=='issuer-client'
  assert 'Conta: conta' in await page.locator('#twitch-token-feedback').inner_text()
  assert 'Anúncios automáticos da Kick habilitados' in await page.locator('#kick-auto-send-state').inner_text()
  attempts=[]
  async def test_send(route):
   payload=route.request.post_data_json
   if payload['text'].startswith('Teste do Sorteador Geral:'):
    attempts.append(payload)
    if len(attempts)==1:
     await route.fulfill(status=502,content_type='application/json',body='{"detail":"A Kick recusou o envio (HTTP 403). Confira chat:write."}')
     return
   await route.fulfill(status=200,content_type='application/json',body='{"ok":true}')
  await page.route('**/api/chat/send',test_send)
  await page.locator('#btn-kick-test-send').click()
  await page.wait_for_timeout(150)
  assert 'HTTP 403' in await page.locator('#kick-test-send-feedback').inner_text()
  await page.locator('#btn-kick-test-send').click()
  await page.wait_for_timeout(150)
  assert 'confirmou o envio' in await page.locator('#kick-test-send-feedback').inner_text()
  assert len(attempts)==2 and all(item['platform']=='kick' for item in attempts)

  await page.evaluate("state.kick.receive_connected=true;state.kick.ngrok_connected=false;state.kick.receive_channel='streamer';state.kick.send_ready=true;state.connections.simulation_mode=false;renderChats();renderLiveChats()")
  await page.locator('.tab[data-tab="chats"]').click()
  assert await page.locator('#kick-status').inner_text()=='operacional'
  assert await page.locator('#kick-live-channel').inner_text()=='@streamer'
  await page.locator('#kick-chat-message').fill('Mensagem local simulada')
  await page.locator('#kick-chat-send').click()
  await page.wait_for_timeout(150)
  assert 'Mensagem enviada' in await page.locator('#kick-chat-feedback').inner_text()
  # Anti-bot: configuração na inscrição, lista, isenção e preservação de rascunhos.
  await page.locator('.tab[data-tab="antibot"]').click()
  assert await page.locator('#antibot-random').count()==0
  if not await page.locator('#antibot-enabled').is_checked(): await page.locator('label[for="antibot-enabled"]').click()
  if not await page.locator('#antibot-waive').is_checked(): await page.locator('label[for="antibot-waive"]').click()
  await page.locator('#antibot-chance').fill('100')
  async with page.expect_response('**/api/antibot/config') as pending:
   await page.locator('#btn-antibot-save').click()
  assert (await pending.value).ok
  await page.request.post('http://127.0.0.1:18777/api/giveaway/start',data={'keyword':'!sorteio'})
  for platform,nick,sub in [('twitch','marcada_twitch',False),('kick','marcada_kick',False),('kick','sub_isento',True)]:
   r=await page.request.post('http://127.0.0.1:18777/api/_debug/inject',data={'platform':platform,'username':nick,'is_sub':sub})
   assert r.ok
  await page.wait_for_timeout(300)
  assert await page.locator('#ab-marked-count').inner_text()=='2'
  assert 'sub_isento' not in await page.locator('#antibot-marked-tbody').inner_text()
  await page.locator('#antibot-marked-platform').select_option('kick')
  assert 'marcada_twitch' not in await page.locator('#antibot-marked-tbody').inner_text()
  await page.locator('#antibot-marked-platform').select_option('')
  await page.locator('#antibot-chance').fill('50')
  await page.evaluate('render()')
  assert await page.locator('#antibot-chance').input_value()=='50'
  await page.locator('#antibot-chance').fill('0')
  async with page.expect_response('**/api/antibot/config') as pending:
   await page.locator('#btn-antibot-save').click()
  assert (await pending.value).ok
  r=await page.request.post('http://127.0.0.1:18777/api/_debug/inject',data={'platform':'kick','username':'entrada_zero'})
  assert r.ok
  await page.wait_for_timeout(300)
  assert await page.locator('#ab-marked-count').inner_text()=='2'
  state=await (await page.request.get('http://127.0.0.1:18777/api/state')).json()
  assert state['antibot']['random_chance']==0
  import os
  capture=os.environ.get('SORTEADOR_QA_SCREENSHOTS')
  if capture:
   await page.evaluate('window.scrollTo(0,0)')
   await page.screenshot(path=capture+'/antibot.png',full_page=True)
   await page.locator('.tab[data-tab="roleta"]').click()
   await page.evaluate('window.scrollTo(0,0)')
   await page.screenshot(path=capture+'/roleta-config.png',full_page=True)
  await page.locator('.tab[data-tab="roleta"]').click()
  assert 'Quantidade de prêmios para este nick' in await page.locator('[data-panel="roleta"]').inner_text()
  await page.locator('.roleta-item .ri-weight').first.fill('0')
  await page.locator('#roleta-duration').fill('1.5')
  await page.locator('#roleta-announce-chat').check()
  await page.locator('#btn-roleta-save-all').click()
  await page.wait_for_timeout(300)
  merged=await (await page.request.get('http://127.0.0.1:18777/api/state')).json()
  assert merged['roleta']['duration_seconds']==1.5 and merged['chat_events']['prize_won']
  assert 'salvos' in await page.locator('#roleta-status').inner_text()
  saved=await (await page.request.get('http://127.0.0.1:18777/api/roleta/items')).json()
  if isinstance(saved,dict): saved=saved['items']
  assert saved[0]['weight']==0
  await page.set_viewport_size({'width':900,'height':1000})
  await page.locator('.tab[data-tab="antibot"]').click()
  assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
  # Primeiro confirma a presença e encerra o relógio; só então aparece captcha.
  await page.request.post('http://127.0.0.1:18777/api/antibot/config',data={'enabled':True,'random_chance':100,'waive_subs_vips':False,'max_attempts':1})
  await page.request.post('http://127.0.0.1:18777/api/giveaway/start',data={'keyword':'!sorteio'})
  await page.request.post('http://127.0.0.1:18777/api/_debug/inject',data={'platform':'kick','username':'captcha_chat'})
  await page.request.post('http://127.0.0.1:18777/api/giveaway/draw',data={})
  current=await (await page.request.get('http://127.0.0.1:18777/api/state')).json()
  deadline=current['giveaway']['winner_deadline']
  assert current['giveaway']['captcha'] is None and deadline>0
  await page.request.post('http://127.0.0.1:18777/api/_test/chat',data={'id':'presence','platform':'kick','username':'captcha_chat','text':'estou aqui'})
  current=await (await page.request.get('http://127.0.0.1:18777/api/state')).json()
  assert current['giveaway']['captcha'] and not current['giveaway']['captcha']['deadline']
  assert current['giveaway']['winner_deadline']==0
  await page.request.post('http://127.0.0.1:18777/api/_test/chat',data={'id':'wrong-1','platform':'kick','username':'captcha_chat','text':'definitely wrong'})
  await page.locator('.tab[data-tab="giveaway"]').click()
  await page.wait_for_timeout(300)
  assert 'incorreta' in await page.locator('#giveaway-captcha-feedback').inner_text()
  current=await (await page.request.get('http://127.0.0.1:18777/api/state')).json()
  assert current['giveaway']['current_winner']['username']=='captcha_chat'
  assert current['giveaway']['winner_deadline']==0
  assert current['giveaway']['captcha'] is None
  assert current['giveaway']['captcha_feedback']['expected']
  await page.request.post('http://127.0.0.1:18777/api/giveaway/captcha/reissue')
  correct=await (await page.request.get('http://127.0.0.1:18777/api/giveaway/captcha/full')).json()
  await page.request.post('http://127.0.0.1:18777/api/_test/chat',data={'id':'correct-captcha','platform':'kick','username':'captcha_chat','text':str(correct['expected'])})
  await page.wait_for_timeout(300)
  assert 'correta' in await page.locator('#giveaway-captcha-feedback').inner_text()
  assert not await page.locator('#giveaway-timer-display').is_visible()
  await page.request.post('http://127.0.0.1:18777/api/giveaway/stop')
  print('Browser errors:',errors);assert not errors
  await browser.close()
if __name__ == '__main__':
 import subprocess,sys
 process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('preview_server.py'))],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 try:
  asyncio.run(main())
 finally:
  process.terminate()
  process.wait(timeout=15)


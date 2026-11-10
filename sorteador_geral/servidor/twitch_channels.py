"""Metadados da colab, seguindo o fluxo do chat de referência enviado.

Cache curto por credencial/canal; chamadas Helix fixas, sem token no navegador.
A ausência de metadados nunca interrompe mensagens ou filtros já conhecidos.
"""
import asyncio
import hashlib
import re
import time
import httpx
from .state import STATE
from .twitch_api import normalize_token

_lock=asyncio.Lock()
_cache={}


def profile(row):
    image=str(row.get('profile_image_url') or '')
    return {'id':str(row.get('id') or ''),'login':str(row.get('login') or '').lower(),
        'display_name':str(row.get('display_name') or row.get('login') or ''),
        'profile_image_url':image if image.startswith('https://') else ''}


async def describe():
    login=STATE.twitch_channel.strip().lstrip('#@').lower()
    fallback={'channel':{'id':'','login':login,'display_name':login,'profile_image_url':''},
        'participants':[],'session_checked':False,'session':None,
        'warning':'Metadados indisponíveis. O chat e os filtros continuam funcionando pelas mensagens recebidas.'}
    token=normalize_token(STATE.bot_twitch_oauth)
    if not re.fullmatch('[a-z0-9_]{1,25}',login) or not token or not STATE.bot_twitch_client_id:return fallback
    key=hashlib.sha256((login+'\0'+STATE.bot_twitch_client_id+'\0'+token).encode()).hexdigest()
    async with _lock:
        cached=_cache.get(key)
        if cached and time.monotonic()-cached[0]<15:return cached[1]
        result=fallback
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                headers={'Client-Id':STATE.bot_twitch_client_id,'Authorization':'Bearer '+token}
                users=await client.get('https://api.twitch.tv/helix/users',params={'login':login},headers=headers)
                rows=users.json().get('data') if users.status_code==200 else None
                if rows:
                    owner=profile(rows[0]);result={**fallback,'channel':owner,'participants':[owner]}
                    response=await client.get('https://api.twitch.tv/helix/shared_chat/session',params={'broadcaster_id':owner['id']},headers=headers)
                    if response.status_code==200:
                        sessions=response.json().get('data') or []
                        session=sessions[0] if sessions else None
                        ids=list(dict.fromkeys([owner['id']]+[str(p.get('broadcaster_id','')) for p in (session or {}).get('participants',[]) if re.fullmatch('[0-9]{1,20}',str(p.get('broadcaster_id','')))]))[:100]
                        participants=[owner]
                        if len(ids)>1:
                            response=await client.get('https://api.twitch.tv/helix/users',params=[('id',value) for value in ids],headers=headers)
                            if response.status_code==200:
                                participants=[profile(p) for p in response.json().get('data',[])]
                                if not any(p['id']==owner['id'] for p in participants):participants.insert(0,owner)
                        result={'channel':owner,'participants':participants,'session_checked':True,
                            'session':{'id':str(session.get('session_id',''))} if session else None,'warning':''}
        except (httpx.HTTPError,ValueError,TypeError,AttributeError,KeyError):pass
        # Keep names previously resolved for a transient outage.
        if not result['session_checked'] and cached:
            result={**cached[1],'session_checked':False,'warning':fallback['warning']}
        _cache[key]=(time.monotonic(),result)
        while len(_cache)>8:del _cache[next(iter(_cache))]
        return result

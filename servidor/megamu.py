"""Consulta de disponibilidade de prêmios, conforme getawards do overlay enviado."""
import asyncio
import hashlib
import html
import json
import logging
import re
import time

import httpx

from . import env_config
from .state import STATE

_lock = asyncio.Lock()
_fingerprint = ''


async def character_info(nick: str) -> str:
    """Consulta pública usada por bots do chat: !nick NomeDoPersonagem.

    O getdata.php é um endpoint separado do dvapi.php de prêmios e não usa
    DV nem chave. Interpreta a confirmação de existência e os níveis exibidos
    pelo getdata.php sem confundir a resposta de personagem inexistente.
    """
    if not re.fullmatch(r'[A-Za-z0-9_-]{2,24}', nick):
        raise ValueError('Informe um nick válido (2 a 24 letras, números, _ ou -).')
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
            response = await client.get('https://megamu.net/getdata.php',
                params={'char': nick, 'default': 'SEUNICK'},
                headers={'Accept': 'text/plain, application/json;q=0.9, */*;q=0.1',
                         'User-Agent': 'SorteadorGeral/0.16'})
        if response.status_code != 200:
            raise ValueError('A consulta de personagem está indisponível no momento.')
        raw = response.text.strip()
        if not raw or raw.upper() == 'SEUNICK':
            raise ValueError(f'{nick} não foi encontrado no MEGAMU.')
        if '<html' in raw.lower() or '<!doctype' in raw.lower():
            raise ValueError('A MegaMu não retornou dados de personagem.')
        # A expressão $(urlfetch ...) do Nightbot espera texto pronto para chat.
        # O backend devolve o texto público, removendo tags e quebras indesejadas.
        clean = html.unescape(re.sub(r'<[^>]*>', ' ', raw))
        clean = re.sub(r'[\x00-\x1f\x7f]+', ' ', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        if not clean:
            raise ValueError('A MegaMu retornou uma resposta vazia.')
        # O getdata.php devolve literalmente "Player não existente." para nicks
        # desconhecidos (HTTP 200 também nesse caso).
        if re.fullmatch(r'Player\s+n[aã]o\s+existente\s*[.!]?', clean, re.IGNORECASE):
            raise ValueError(f'O personagem {nick} não existe no MEGAMU.')
        match = re.fullmatch(
            r'\[(?P<name>[^\]]{2,32})\]\s*(?P<level>\d+)\s*\(\s*(?P<rr>\d+)\s*rr\s*\)\s*,\s*HuntLevel\s*:\s*(?P<hunt>\d+)',
            clean, re.IGNORECASE,
        )
        if match:
            data = match.groupdict()
            return (f"✅ {data['name']} existe no MEGAMU! "
                    f"⚔️ Nível {data['level']} | 🔄 {data['rr']} RR | 🎯 Hunt {data['hunt']}")
        # Formatos antigos/customizados continuam sendo mostrados como texto,
        # sem afirmar que o personagem existe se o esquema é desconhecido.
        return clean[:320] + ('…' if len(clean) > 320 else '')
    except httpx.HTTPError:
        raise ValueError('Não foi possível consultar a MegaMu agora.') from None


class _RedactKeys(logging.Filter):
    def filter(self, record):
        record.msg = re.sub(r'([?&](?:key|dv)=)[^&\s"\']+', r'\1[oculto]', record.getMessage())
        record.args = ()
        return True


logging.getLogger('httpx').addFilter(_RedactKeys())


def status():
    saved = env_config.read()
    return {'dv':saved.get('MEGAMU_DV',''), 'has_key':bool(saved.get('MEGAMU_KEY')),
        'enabled':saved.get('MEGAMU_ENABLED','false').lower() == 'true',
        'awards':STATE.megamu_awards, 'updated_at':STATE.megamu_updated_at,
        'error':STATE.megamu_error}


async def refresh():
    global _fingerprint
    saved = env_config.read()
    dv, key = saved.get('MEGAMU_DV',''), saved.get('MEGAMU_KEY','')
    if not dv or not key:
        raise ValueError('Preencha o DV e a chave da MegaMu em Conexões.')
    fingerprint = hashlib.sha256((dv+'\0'+key).encode()).hexdigest()
    async with _lock:
        if fingerprint == _fingerprint and STATE.megamu_updated_at and time.time()-STATE.megamu_updated_at < 5:
            return status()
        try:
            async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
                response = await client.get('https://megamu.net/dvapi.php',
                    params={'dv':dv, 'key':key, 'action':'getawards'},
                    headers={'Accept':'application/json','User-Agent':'SorteadorGeral/0.11'})
            if response.status_code != 200:
                raise ValueError(f'A MegaMu recusou a consulta (HTTP {response.status_code}).')
            data = response.json()
            if not isinstance(data,dict) or str(data.get('result')) != '1':
                code = data.get('result') if isinstance(data,dict) else None
                raise ValueError('DV ou chave incorretos na MegaMu.' if str(code)=='-101' else 'A MegaMu não confirmou a consulta de prêmios.')
            awards = data.get('awards')
            if not isinstance(awards,list):
                raise ValueError('A MegaMu retornou um catálogo em formato inesperado.')
            names = []
            for item in awards:
                if not isinstance(item,dict) or not isinstance(item.get('name'),str) or not item['name'].strip():
                    raise ValueError('A MegaMu retornou itens em formato inesperado. A lista anterior foi mantida.')
                name = item['name'].strip()[:200]
                if name and name not in names:names.append(name)
            STATE.megamu_awards = [{'name':name,'icon':'🎁'} for name in names[:500]]
            STATE.megamu_updated_at = time.time()
            STATE.megamu_error = ''
            _fingerprint = fingerprint
            from . import giveaway_prizes
            await giveaway_prizes.reconcile()
            return status()
        except (httpx.HTTPError, ValueError, TypeError) as error:
            message = str(error) if isinstance(error,ValueError) and not isinstance(error, json.JSONDecodeError) else 'Não foi possível consultar a MegaMu. Tente novamente.'
            STATE.megamu_error = message
            raise ValueError(message) from None

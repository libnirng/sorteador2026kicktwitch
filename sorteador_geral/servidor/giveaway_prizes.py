"""Prêmios próprios e catálogo externo têm origens e permissões separadas."""
import hashlib
import time
import uuid

from . import db, env_config
from .state import STATE


def available():
    remote = []
    if env_config.read().get('MEGAMU_ENABLED','false').lower() == 'true':
        remote = [{'id':'megamu:'+hashlib.sha256(p['name'].encode()).hexdigest()[:24],
                   'name':p['name'],'source':'megamu'} for p in STATE.megamu_awards]
    return remote + [dict(p,source='custom') for p in STATE.custom_giveaway_prizes]


async def add(name):
    prize={'id':'custom:'+uuid.uuid4().hex,'name':name.strip()}
    STATE.custom_giveaway_prizes.append(prize)
    await db.config_set('custom_giveaway_prizes',STATE.custom_giveaway_prizes)
    return dict(prize,source='custom')


async def remove(prize_id):
    if not prize_id.startswith('custom:'):
        raise ValueError('Prêmios MegaMu só saem quando a API informar que não estão mais disponíveis.')
    if not any(p['id']==prize_id for p in STATE.custom_giveaway_prizes):
        raise LookupError('Prêmio personalizado não encontrado.')
    STATE.custom_giveaway_prizes[:]=[p for p in STATE.custom_giveaway_prizes if p['id']!=prize_id]
    await db.config_set('custom_giveaway_prizes',STATE.custom_giveaway_prizes)
    if STATE.selected_giveaway_prize and STATE.selected_giveaway_prize['id']==prize_id:
        STATE.selected_giveaway_prize=None
        await db.config_set('selected_giveaway_prize',None)


def selected():
    if STATE.selected_giveaway_prize:
        return next((p for p in available() if p['id']==STATE.selected_giveaway_prize['id']),None)
    return None


async def select(prize_id):
    prize=next((p for p in available() if p['id']==prize_id),None)
    if not prize:raise LookupError('Este prêmio não está mais disponível. Atualize a lista.')
    STATE.selected_giveaway_prize={**prize,'selected_at':time.time()}
    await db.config_set('selected_giveaway_prize',STATE.selected_giveaway_prize)
    return prize


async def reconcile():
    """Uma resposta válida da API remove seleções que saíram do catálogo."""
    async with STATE.lock:
        if STATE.selected_giveaway_prize and not selected():
            STATE.selected_giveaway_prize=None
            await db.config_set('selected_giveaway_prize',None)

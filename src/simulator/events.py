from __future__ import annotations

import numpy as np
import pandas as pd
from src.simulator.catalog import leaves


def make_events(cfg: dict, products: pd.DataFrame, users: pd.DataFrame,
                rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Vectorized rounds: each user occurs once per round, preserving per-user Markov causality."""
    sim=cfg['simulator'];n=sim['n_users'];total=sim['n_events'];taxonomy=leaves(cfg)
    brands=sim['brands'];persona_names=list(sim['personas']);persona_ids=np.array([persona_names.index(x) for x in users.persona]);user_ids=users.user_id.to_numpy();product_ids=products.product_id.to_numpy()
    brand_to_id={x:i for i,x in enumerate(brands)}
    leaf_to_id={x[2]:i for i,x in enumerate(taxonomy)}
    product_leaves=np.array([leaf_to_id[x] for x in products.category_l3])
    product_brands=np.array([brand_to_id[x] for x in products.brand])
    pools={(l,b):np.flatnonzero((product_leaves==l)&(product_brands==b))
           for l in range(len(taxonomy)) for b in range(len(brands))}
    l1_names=list(sim['taxonomy'])
    # Hidden generator preferences stay local; they never become recommendation profile columns.
    preferred_leaf=np.empty(n,dtype=int)
    for persona,spec in sim['personas'].items():
        group=np.flatnonzero(users.persona.to_numpy()==persona)
        l1=rng.choice(len(l1_names),len(group),p=spec['category_preferences'])
        for l1_id in range(len(l1_names)):
            slots=group[l1==l1_id]
            choices=[i for i,value in enumerate(taxonomy) if value[0]==l1_names[l1_id]]
            preferred_leaf[slots]=rng.choice(choices,len(slots))
    preferred_brand=rng.integers(len(brands),size=n)
    states=np.full(n,'search',dtype='<U8');focus=np.zeros(n,dtype=int)
    sessions=np.ones(n,dtype=int);seen_count=np.zeros(n,dtype=int)
    cold=np.zeros(n,dtype=bool);cold[rng.choice(n,int(n*sim['cold_user_ratio']),replace=False)]=True
    created=products.created_at.astype('int64').to_numpy()
    ref=pd.Timestamp(sim['reference_time']).value
    start=ref-pd.Timedelta(days=sim['window_days']).value
    cold_limit=sim['cold_max_events'];choice=sim['choice_model'];alpha=choice['zipf_alpha']
    rows=[];impression_rows=[];offset=0
    prices_all=products.price.to_numpy()
    step_ns=(ref-start)//total
    while offset<total:
        active=np.flatnonzero((~cold)|(seen_count<cold_limit))
        if len(active)==0:
            raise ValueError('no eligible users for requested event count')
        ids=rng.permutation(active)[:total-offset];m=len(ids)
        # Divide first: multiplying a nanosecond window by event indices overflows int64.
        now=start+np.arange(offset,offset+m,dtype=np.int64)*step_ns
        fresh=(states[ids]=='search')|(states[ids]=='exit')
        fresh_ids=ids[fresh]
        if len(fresh_ids):
            leaf=preferred_leaf[fresh_ids].copy();brand=preferred_brand[fresh_ids].copy()
            discover=rng.random(len(fresh_ids))>choice['preferred_leaf_probability']
            leaf[discover]=rng.integers(len(taxonomy),size=discover.sum())
            diverse=rng.random(len(fresh_ids))>choice['preferred_brand_probability']
            brand[diverse]=rng.integers(len(brands),size=diverse.sum())
            keys=(leaf*len(brands)+brand)*len(persona_names)+persona_ids[fresh_ids]
            for key in np.unique(keys):
                positions=np.flatnonzero(keys==key);pair,pid=divmod(int(key),len(persona_names));l,b=divmod(pair,len(brands));pool=pools[l,b]
                if not len(pool): pool=np.flatnonzero(product_leaves==l)
                if not len(pool): pool=np.arange(len(products))
                # Stable within-group item demand; all items retain nonzero probability.
                available=pool[created[pool]<=int(now[fresh].min())]
                if not len(available): available=np.flatnonzero(created<=int(now[fresh].min()))
                weights=np.arange(1,len(available)+1,dtype=float)**(-alpha)
                sensitivity=sim['personas'][persona_names[pid]]['price_sensitivity']
                prices=prices_all[available]
                weights*=np.exp(-4*sensitivity*(prices/prices.max()))
                weights/=weights.sum()
                focus[fresh_ids[positions]]=rng.choice(available,len(positions),p=weights)
            noise=rng.random(len(fresh_ids))<choice['uniform_noise']
            if noise.any():
                available=np.flatnonzero(created<=int(now[fresh].min()))
                focus[fresh_ids[noise]]=rng.choice(available,int(noise.sum()))
            sessions[fresh_ids]+= (states[fresh_ids]=='exit').astype(int)
            states[fresh_ids]='search'
        event_types=states[ids].copy()
        for local,u in enumerate(ids):
            idx=offset+local;etype=event_types[local];item=int(focus[u]);pid=product_ids[item]
            impression_id=f'I{idx:09d}-0' if etype=='view' else None
            session=f'{user_ids[u]}-S{sessions[u]:05d}'
            query=products.description_en.iloc[item] if etype=='search' else None
            rows.append((f'E{idx:09d}',user_ids[u],None if etype=='search' else pid,etype,
                         int(now[local]),session,query,impression_id,1 if etype=='view' else None))
            if etype=='view':
                impression_rows.append((impression_id,f'R{idx:09d}',user_ids[u],pid,int(now[local]),1))
        view_positions=np.flatnonzero(event_types=='view')
        if len(view_positions):
            exposed_at=now[view_positions]
            extra=rng.integers(len(products),size=(len(view_positions),sim['impressions_per_view']-1))
            bad=(created[extra]>exposed_at[:,None])|(extra==focus[ids[view_positions],None])
            for column in range(1,extra.shape[1]):
                bad[:,column]|=(extra[:,column,None]==extra[:,:column]).any(axis=1)
            while bad.any():
                extra[bad]=rng.integers(len(products),size=bad.sum())
                bad=(created[extra]>exposed_at[:,None])|(extra==focus[ids[view_positions],None])
                for column in range(1,extra.shape[1]):
                    bad[:,column]|=(extra[:,column,None]==extra[:,:column]).any(axis=1)
            for pos,items in zip(view_positions,extra):
                idx=offset+int(pos);u=ids[pos]
                for rank,item in enumerate(items,start=2):
                    impression_rows.append((f'I{idx:09d}-{rank-1}',f'R{idx:09d}',user_ids[u],product_ids[item],int(now[pos]),rank))
        # Persona-dependent transitions: conversion parameters affect actual purchase outcomes.
        for state in ['search','view','cart','purchase']:
            for persona,spec in sim['personas'].items():
                group=ids[(event_types==state)&(users.persona.to_numpy()[ids]==persona)]
                if not len(group):continue
                transitions=dict(sim['transitions'][state])
                if state=='cart':
                    p=float(np.clip(spec['cvr']*9,0.05,0.9))
                    remainder=1-p
                    transitions={'purchase':p,'view':remainder*.45,'exit':remainder*.55}
                labels=list(transitions);probs=np.array(list(transitions.values()),dtype=float);probs/=probs.sum()
                states[group]=rng.choice(labels,len(group),p=probs)
        seen_count[ids]+=1;offset+=m
    events=pd.DataFrame(rows,columns=['event_id','user_id','product_id','event_type','timestamp','session_id','query','impression_id','position'])
    events['timestamp']=pd.to_datetime(events.timestamp,utc=True)
    impressions=pd.DataFrame(impression_rows,columns=['impression_id','request_id','user_id','product_id','exposed_at','position'])
    impressions['exposed_at']=pd.to_datetime(impressions.exposed_at,utc=True)
    return events,impressions

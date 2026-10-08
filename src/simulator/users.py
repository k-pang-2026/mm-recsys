from __future__ import annotations

import numpy as np
import pandas as pd


def make_users(cfg: dict, rng: np.random.Generator) -> pd.DataFrame:
    sim=cfg['simulator'];n=sim['n_users']
    names=list(sim['personas']);ratios=np.array([sim['personas'][x]['ratio'] for x in names])
    counts=np.floor(ratios*n).astype(int);counts[-1]+=n-counts.sum()
    personas=np.repeat(names,counts);rng.shuffle(personas)
    ref=pd.Timestamp(sim['reference_time'])
    return pd.DataFrame({'user_id':[f'U{i+1:06d}' for i in range(n)],'persona':personas,
                         'age_group':rng.choice(['18-24','25-34','35-44','45+'],n),
                         'gender':rng.choice(['F','M','unspecified'],n),
                         'signup_at':ref-pd.to_timedelta(rng.integers(60,300,n),unit='D')})

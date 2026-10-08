from __future__ import annotations

import pandas as pd


def chronological_split(events: pd.DataFrame, fractions: dict) -> dict[str,pd.DataFrame]:
    ordered=events.sort_values(['timestamp','event_id'],kind='stable').reset_index(drop=True)
    n=len(ordered);a=int(n*fractions['train']);b=int(n*(fractions['train']+fractions['valid']))
    # Ties remain together. The generator normally has unique timestamps.
    for boundary in ('a','b'):
        index=a if boundary=='a' else b
        while 0<index<n and ordered.timestamp.iloc[index]==ordered.timestamp.iloc[index-1]: index+=1
        if boundary=='a':a=index
        else:b=max(a,index)
    return {'train':ordered.iloc[:a].copy(),'valid':ordered.iloc[a:b].copy(),'test':ordered.iloc[b:].copy()}

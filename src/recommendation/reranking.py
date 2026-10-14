"""Cold start, new items, bandit slots, then quota-preserving diversity repair."""
from __future__ import annotations

from dataclasses import dataclass, replace
from collections import Counter
import math
from typing import Protocol
import numpy as np
import pandas as pd

from src.recommendation.mab import create_strategy


@dataclass(frozen=True)
class RankedItem:
    product_id: str
    score: float
    reason: str = 'DeepFM 클릭·구매 가능성'
    is_exploration: bool = False


class RerankStrategy(Protocol):
    def apply(self, items: list[RankedItem], **context) -> list[RankedItem]: ...


class ColdStart:
    def apply(self,items,**context):
        score=context['fallback_scores']
        return [replace(item,score=float(score.get(item.product_id,0)),reason='인기·최근 상승 상품')
                for item in sorted(items,key=lambda x:(-score.get(x.product_id,0),x.product_id))]


def diversity_capacity(counts: dict[str, int],limit: int,tail: str | None=None,run: int=0) -> int:
    total=sum(counts.values())
    return min([total]+[(limit+1)*(total-number)+limit-(run if category==tail else 0)
                        for category,number in counts.items() if number>0])


def completion_feasible(counts: dict[str, int],required: dict[str, int],slots: int,
                        limit: int,tail: str | None,run: int) -> bool:
    if slots<sum(required.values()) or diversity_capacity(counts,limit,tail,run)<slots:
        return False
    if any(number>counts.get(category,0) for category,number in required.items()): return False
    total_required=sum(required.values())
    separators=max([0]+[math.ceil(max(0,number-(limit-(run if category==tail else 0))
                                            -limit*(total_required-number))/limit)
                         for category,number in required.items() if number>0])
    return total_required+separators<=slots


class Reranker:
    def __init__(self,cfg: dict,products: pd.DataFrame):
        self.cfg=cfg; self.spec=cfg['recommend']; field=self.spec['reranking']['category_field']
        if field not in ('category_l2','category_l3'): raise ValueError('unsupported diversity category')
        self.categories=products.set_index('product_id')[field].astype(str).to_dict()
        self.created=products.set_index('product_id').created_at.to_dict()
        self.bandit=create_strategy(self.spec['mab']); self.cold=ColdStart()
        if set(self.spec['reranking']['pipeline'])!={'cold_start','new_item','exploration','diversity'} or self.spec['reranking']['pipeline'][-1]!='diversity':
            raise ValueError('pipeline must include all strategies and finish with diversity')
        if self.spec['reranking']['cold_sort']!='popularity_growth': raise ValueError('unsupported cold sort')
        if self.spec['max_consecutive_same_category']<1 or self.spec['mab']['exploration_slots']<0:
            raise ValueError('invalid reranking quotas')

    def run(self,items: list[RankedItem],top_n: int,at: pd.Timestamp,history_count: int,
            fallback_scores: dict,stats: dict,arm_for,rng: np.random.Generator) -> tuple[list[RankedItem],dict]:
        if top_n<1: raise ValueError('top_n must be positive')
        unique={}
        for item in items:
            if item.product_id not in self.created or self.created[item.product_id]>at: continue
            unique.setdefault(item.product_id,item)
        pool=sorted(unique.values(),key=lambda x:(-x.score,x.product_id))
        count=min(top_n,len(pool)); slots=min(2,self.spec['mab']['exploration_slots'],count)
        new={item.product_id for item in pool if at-pd.Timedelta(days=self.spec['new_item_days'])<=self.created[item.product_id]<=at}
        selected_ids=[]; new_anchor=None
        for stage in self.spec['reranking']['pipeline'][:-1]:
            if stage=='cold_start' and history_count<self.spec['cold_start_min_events']:
                pool=self.cold.apply(pool,fallback_scores=fallback_scores)
            elif stage=='new_item' and new:
                new_anchor=next(item.product_id for item in pool if item.product_id in new)
            elif stage=='exploration':
                selected_ids=self.bandit.select([item.product_id for item in pool],stats,arm_for,rng,slots)
        # At small N a new item can satisfy both quotas in the same slot.
        if new and slots and not (set(selected_ids)&new):
            selected_ids[-1]=new_anchor
        mandatory=set(selected_ids)
        if new and count and not mandatory&new:
            mandatory.add(new_anchor)
        mapped={item.product_id:replace(item,is_exploration=item.product_id in selected_ids,
                reason='MAB 탐색' if item.product_id in selected_ids else '신상품 추천' if item.product_id in mandatory&new else item.reason) for item in pool}
        # Reserve all quotas before filling; repair from the entire distinct candidate pool.
        limit=self.spec['max_consecutive_same_category']; output=[]; remaining=set(mapped); required=set(mandatory)
        available=Counter(self.categories[p] for p in remaining)
        initial_counts=dict(available)
        capacity=diversity_capacity(available,limit)
        diagnostics=[]
        while len(output)<count:
            tail=self.categories[output[-1].product_id] if output else None
            run=0
            for previous in reversed(output):
                if self.categories[previous.product_id]!=tail: break
                run+=1
            feasible=[item.product_id for item in pool if item.product_id in remaining and not (run>=limit and self.categories[item.product_id]==tail)]
            must_take=len(required)>=count-len(output)
            candidates=[p for p in feasible if p in required] if must_take else feasible
            if not candidates:
                candidates=[p for p in remaining if p in required] if required else list(remaining)
                if not candidates: break
                diagnostics.append('diversity_infeasible_with_remaining_quotas')
            # Avoid leaving many required items of the same category to the last slots.
            def priority(p):
                category=self.categories[p]
                required_cat=sum(self.categories[q]==category for q in required)
                return (p in required and required_cat>max(1,(count-len(output))//2),p in required,mapped[p].score,p)
            chosen=None; cache={}
            for product in sorted(candidates,key=priority,reverse=True):
                category=self.categories[product]; key=(category,product in required)
                if key not in cache:
                    after=available.copy(); after[category]-=1
                    quota=Counter(self.categories[p] for p in required if p!=product)
                    next_run=run+1 if category==tail else 1
                    cache[key]=completion_feasible(after,quota,count-len(output)-1,limit,category,next_run)
                if cache[key]: chosen=product; break
            if chosen is None:
                chosen=max(candidates,key=priority)
                diagnostics.append('diversity_infeasible_with_remaining_quotas')
            output.append(mapped[chosen]); remaining.remove(chosen); required.discard(chosen)
            available[self.categories[chosen]]-=1
        ids=[x.product_id for x in output]
        violations=[]
        if len(ids)!=len(set(ids)): violations.append('duplicate')
        if new and output and not set(ids)&new: violations.append('new_item_missing')
        if sum(x.is_exploration for x in output)!=slots: violations.append('exploration_quota')
        if any(len({self.categories[p] for p in ids[i:i+limit+1]})==1 for i in range(len(ids)-limit)):
            violations.append('diversity')
        if not new: diagnostics.append('new_item_unavailable_in_candidate_pool')
        if len(pool)<top_n: diagnostics.append('insufficient_distinct_candidates')
        return output,dict(requested=top_n,returned=len(output),exploration_slots=slots,new_available=len(new),
                           diversity_capacity=capacity,diversity_feasible_for_returned=capacity>=count,
                           candidate_category_counts=initial_counts,
                           diagnostics=sorted(set(diagnostics)),violations=violations,
                           status='PASS' if not violations else 'INFEASIBLE')

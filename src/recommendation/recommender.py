"""One loaded candidate/ranking/session pipeline, batched over 300 candidates."""
from __future__ import annotations

from typing import Any

import threading
import time
import numpy as np
import pandas as pd
import torch

from src.common.schemas import RecommendResponse,RecommendationItem,PipelineLatency,SessionContext
from src.recommendation.candidate import FaissCandidate
from src.recommendation.datasets import context_for,padded_history
from src.recommendation.ranking_features import HistoryIndex
from src.recommendation.reranking import Reranker,RankedItem
from src.recommendation.session import sequence_for
from src.recommendation.scoring import score_items, policy


class Recommender:
    def __init__(self,cfg: dict,store,data: dict,candidate,encoder,table,index,ranker,ranking_encoder,session_model=None,at: pd.Timestamp | None=None,history: pd.DataFrame | None=None) -> None:
        self.cfg,self.store,self.data=cfg,store,data
        self.scoring=policy(cfg['recommend'].get('scoring'))
        self.candidate_model,self.encoder,self.table=candidate,encoder,table
        self.ranker,self.ranking_encoder,self.session_model=ranker,ranking_encoder,session_model
        self.at=pd.Timestamp(at or cfg['simulator']['reference_time'])
        self.history=history if history is not None else pd.concat([data['train'],data['valid']],ignore_index=True)
        self.history=self.history[self.history.timestamp<self.at]
        self.groups={str(uid):group for uid,group in self.history.groupby('user_id',sort=False)}
        self.user_rows=data['users'].set_index('user_id').to_dict('index')
        self.history_index=HistoryIndex(self.history,table,popularity_events=data['train'])
        self.candidate=FaissCandidate(candidate,table,table.eligible(self.at),index)
        self.reranker=Reranker(cfg,data['products']); self.rng=np.random.default_rng(cfg['seed']+20)
        self._lock=threading.RLock(); self.last_diagnostics: dict = {}
        self.ct_version: str = "v1.0"
        self.exposure_clock: list[float] = [0.0]
        train=data['train'][data['train'].timestamp<self.at]
        counts=train[train.product_id.notna()].product_id.value_counts()
        anchor=train.timestamp.max(); trend_days=cfg['recommend']['reranking']['trend_days']
        recent=train[train.timestamp>=anchor-pd.Timedelta(days=trend_days)].product_id.value_counts()
        previous=train[(train.timestamp<anchor-pd.Timedelta(days=trend_days)) & (train.timestamp>=anchor-pd.Timedelta(days=2*trend_days))].product_id.value_counts()
        growth_weight=cfg['recommend']['reranking']['growth_weight']
        max_count=max(float(counts.max()),1.) if len(counts) else 1.
        self.fallback_scores={pid:float(counts.get(pid,0))/max_count+growth_weight*max(float(recent.get(pid,0)-previous.get(pid,0)),0)/max_count for pid in table.ids[1:]}
        self.fallback_sorted=sorted(self.fallback_scores,key=lambda p:(-self.fallback_scores[p],p))

    def context(self,user_id: str,recent_clicks: list[str]) -> Any:
        context=context_for(self.groups.get(user_id,self.history.iloc[:0]),self.user_rows.get(user_id),self.encoder,self.table,self.at,self.cfg['recommend']['candidate']['history_n'])
        known=[self.table.id_to_index[p] for p in recent_clicks if p in self.table.id_to_index and self.table.created[self.table.id_to_index[p]]<=self.at.value]
        if known:
            prior=context.history[context.history!=0].tolist()
            context.history=padded_history(prior+known,self.cfg['recommend']['candidate']['history_n'])
            context.history_count+=len(known)
        return context

    def candidate_products(self,user_context: Any,features: Any) -> list[str]:
        k=self.cfg['recommend']['candidate_k']
        if user_context.history_count<self.cfg['recommend']['cold_start_min_events']:
            allowed=self.candidate.allowed
            products=[p for p in self.fallback_sorted if self.table.id_to_index[p] in allowed][:k]
        else:
            vector=self.candidate.user_vectors([user_context])
            if self.session_model is not None and features.recent_clicks:
                vector=self.session_model.combine(vector,sequence_for(features.recent_clicks,self.table,self.cfg['recommend']['session']['max_length']),self.cfg['recommend']['session'])
            products=self.candidate.search(vector,k,user_context.purchased if self.cfg['recommend']['exclude_purchased'] else frozenset())[0]
        return products

    def predict_products(self,user_id: str,products: list[str],features: Any) -> np.ndarray:
        if not products: return np.empty((0,2),dtype=np.float32)
        sparse,dense=self.ranking_encoder.serving(user_id,products,self.at,self.data['users'],self.table,self.history_index,features.recent_clicks,features.session_clicks,user_rows=self.user_rows)
        probabilities=self.ranker(torch.from_numpy(sparse),torch.from_numpy(dense)).sigmoid().numpy()
        return probabilities

    def rank_products(self,products: list[str],probabilities: Any) -> list[RankedItem]:
        return score_items(products,probabilities,self.scoring)

    def rerank_items(self,items: Any,top_n: int,user_context: Any) -> tuple[list[RankedItem], dict]:
        if self.cfg['recommend'].get('enable_reranking',True):
            scoped = [item.product_id for item in items] if self.cfg['recommend']['mab']['algo'] == 'epsilon_greedy' else None
            stats=self.store.arm_statistics(scoped) if hasattr(self.store,'arm_statistics') else {}
            arm_for=self.store.arm_for if hasattr(self.store,'arm_for') else lambda p:p
            items,diagnostics=self.reranker.run(items,top_n,self.at,user_context.history_count,self.fallback_scores,stats,arm_for,self.rng)
        else:
            items=sorted(items,key=lambda x:(-x.score,x.product_id))[:top_n]; diagnostics={'status':'B4_PASS_THROUGH'}
        return items,diagnostics

    def recommend(self,user_id: str,top_n: int) -> RecommendResponse:
        if not 1<=top_n<=100: raise ValueError('top_n must be 1..100')
        with self._lock,torch.inference_mode():
            started=time.perf_counter(); features=self.store.get_features(user_id)
            # The shared FeatureStore profile may add known user demographics (C warmup).
            user_context=self.context(user_id,features.recent_clicks)
            if user_id not in self.user_rows and features.profile:
                row=dict(features.profile,signup_at=self.at)
                if all(f in row for f in ['age_group','gender']):
                    user_context.demographics=self.encoder.demographics(row,self.at)
            products=self.candidate_products(user_context,features)
            candidate_done=time.perf_counter()
            probabilities=self.predict_products(user_id,products,features)
            items=self.rank_products(products,probabilities)
            ranking_done=time.perf_counter()
            items,diagnostics=self.rerank_items(items,top_n,user_context)
            # C-MAB-001: shared memory/Redis needs this exposure contract for live learning.
            if self.cfg['recommend'].get('record_exposures',True) and hasattr(self.store,'record_exposures'):
                recorded = self.store.record_exposures(user_id,[item.product_id for item in items])
                diagnostics['mab_connection'] = 'CONNECTED' if len(recorded) == len(items) else 'UNAVAILABLE'
            else: diagnostics['mab_connection']='UNCONNECTED; C-MAB-001/C-SESSION-002 OPEN'
            ended=time.perf_counter(); self.last_diagnostics=diagnostics
            interest=features.session_interest
            if features.recent_clicks:
                latest=next((p for p in reversed(features.recent_clicks) if p in self.reranker.categories),None)
                if latest: interest=self.reranker.categories[latest]
            return RecommendResponse(user_id=user_id,recommendations=[RecommendationItem(product_id=x.product_id,score=x.score,reason=x.reason,is_exploration=x.is_exploration) for x in items],
                    pipeline_latency=PipelineLatency(candidate_ms=(candidate_done-started)*1000,ranking_ms=(ranking_done-candidate_done)*1000,
                            reranking_ms=(ended-ranking_done)*1000,total_ms=(ended-started)*1000),
                    session_context=SessionContext(recent_clicks=features.recent_clicks,session_interest=interest))

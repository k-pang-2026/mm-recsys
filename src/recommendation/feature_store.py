"""B-owned memory adapter for C-MAB-001/C-SESSION-002; shared server stays unchanged."""
from __future__ import annotations

from collections import defaultdict
import time

from src.serving.memory_store import MemoryFeatureStore


class RecommendationFeatureStore(MemoryFeatureStore):
    def __init__(self, cfg: dict, products=None, clock=time.monotonic):
        serving=cfg['serving']
        super().__init__(serving['history_limit'],serving['session_ttl_seconds'],serving['feedback_ttl_seconds'],clock)
        self.spec=dict(cfg['recommend']['mab'])
        if self.spec['arm'] not in ('item','category'): raise ValueError('unsupported MAB arm')
        field=cfg['recommend']['reranking']['category_field']
        self.categories={} if products is None else products.set_index('product_id')[field].astype(str).to_dict()
        self._arms=defaultdict(lambda:dict(exposures=0,reward=0.))
        self._exposures={}; self._sequence=0; self.unattributed_feedback=0

    def arm_for(self, product_id: str) -> str:
        return product_id if self.spec['arm']=='item' else self.categories.get(product_id,'unknown')

    def append_event(self,event) -> bool:
        if event.category is None and event.product_id in self.categories:
            event=event.model_copy(update={'category':self.categories[event.product_id]})
        return super().append_event(event)

    def record_exposures(self,user_id: str,product_ids: list[str]) -> list[str]:
        with self._lock:
            now=self.clock()
            self._exposures={key:value for key,value in self._exposures.items() if value['expires']>now}
            identifiers=[]
            for product in dict.fromkeys(product_ids):
                self._sequence+=1; identifier=f'b-exposure-{self._sequence}'
                arm=self.arm_for(product); self._arms[arm]['exposures']+=1
                self._exposures[(user_id,product)]=dict(identifier=identifier,arm=arm,reward=0.,expires=now+self.spec['exposure_ttl_seconds'])
                identifiers.append(identifier)
            return identifiers

    def arm_statistics(self) -> dict:
        with self._lock: return {key:dict(value) for key,value in self._arms.items()}

    def update_reward(self,feedback) -> bool:
        with self._lock:
            now=self.clock(); self._expire(now); key=('feedback',feedback.event_id)
            if key in self._seen: return False
            self._seen[key]=now+self.feedback_ttl
            exposure=self._exposures.get((feedback.user_id,feedback.product_id))
            if exposure is None or exposure['expires']<=now:
                self.unattributed_feedback+=1; return True
            reward=self.spec['click_reward'] if feedback.event_type=='view' else self.spec['purchase_reward'] if feedback.event_type=='purchase' else 0.
            increase=max(float(reward)-exposure['reward'],0.)
            self._arms[exposure['arm']]['reward']+=increase
            exposure['reward']=max(exposure['reward'],float(reward))
            return True

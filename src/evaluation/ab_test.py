"""Seeded local A/B simulation over real B5 policies, with isolated arm state.

No test outcomes or latent simulator preferences are supplied to recommenders.
Outcome-model persona parameters are simulation hypotheses, not measured lift.
"""
from __future__ import annotations

from typing import Any

import argparse
import copy
import hashlib
import json
import os
import platform
import threading
from types import MappingProxyType
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol, Sequence, TypedDict, cast

import numpy as np
import pandas as pd

from src.common.artifacts import file_hash, fingerprint, write_json
from src.common.config import load_config
from src.common.schemas import FeedbackRequest, RecommendationItem
from src.evaluation.ab_statistics import binary_comparison, clustered_rate

VERSION = 'user-randomized-ab-v1'


def stream_seed(seed: int, *keys: object) -> int:
    digest = hashlib.sha256(json.dumps([seed, *keys], separators=(',', ':')).encode()).digest()
    return int.from_bytes(digest[:8], 'big')


def assign_users(user_ids: list[str], seed: int, per_group: int) -> dict[str, list[str]]:
    if per_group < 2 or len(set(user_ids)) != len(user_ids) or len(user_ids) < 2 * per_group:
        raise ValueError('unique population with at least two users per arm required')
    ordered = sorted(user_ids, key=lambda uid: (stream_seed(seed, 'assignment', uid), uid))
    return {'control': ordered[:per_group], 'treatment': ordered[per_group:2 * per_group]}


class Policy(Protocol):
    store: Any
    def recommend(self, user_id: str, top_n: int, at: pd.Timestamp,
                  policy_seed: int) -> list[RecommendationItem]: ...


class UserIsolatedStore:
    """Keep adaptive learning inside each independent randomized user cluster.

    A shared arm-wide bandit would make one user's outcomes alter another's
    treatment. Its experiment-level inference would require a different design.
    The B5 store/reward implementation itself is reused unchanged per user.
    """
    def __init__(self, cfg: dict, products: pd.DataFrame, clock):
        self.cfg, self.products, self.clock = cfg, products, clock
        field = cfg['recommend']['reranking']['category_field']
        self.categories = MappingProxyType(products.set_index('product_id')[field].astype(str).to_dict())
        self.users: dict[str, Any] = {}
        self.active: str | None = None

    def user_store(self, uid: str) -> Any:
        from src.recommendation.feature_store import RecommendationFeatureStore
        if uid not in self.users:
            store = RecommendationFeatureStore(self.cfg, clock=self.clock)
            # Catalog metadata is immutable; only each user's adaptive state is private.
            # Avoid copying the full catalog once per randomized user at full scale.
            store.categories = self.categories
            self.users[uid] = store
        return self.users[uid]

    def get_features(self, uid: str) -> Any:
        self.active = uid
        return self.user_store(uid).get_features(uid)

    def record_exposures(self, uid: str, products: list[str]) -> list[str]:
        self.active = uid
        return self.user_store(uid).record_exposures(uid, products)

    def arm_statistics(self, product_ids: list[str] | None = None) -> dict:
        return self.user_store(self.active).arm_statistics(product_ids) if self.active is not None else {}

    def arm_for(self, product: str) -> str:
        if self.active is None:
            raise ValueError('select a user before querying bandit arms')
        return self.user_store(self.active).arm_for(product)

    def append_event(self, event: Any) -> bool:
        return self.user_store(event.user_id).append_event(event)

    def update_reward(self, event: Any) -> bool:
        return self.user_store(event.user_id).update_reward(event)

    def experiment_statistics(self) -> dict:
        return {f'{uid}:{key}': value for uid, store in self.users.items()
                for key, value in store.arm_statistics().items()}

    @property
    def unattributed_feedback(self) -> int:
        return sum(store.unattributed_feedback for store in self.users.values())


class ModelPolicy:
    def __init__(self, service, strategy: str, train: pd.DataFrame):
        self.service, self.store, self.strategy = service, service.store, strategy
        counts = train[train.product_id.notna()].product_id.value_counts()
        self.popular = sorted(service.table.ids[1:], key=lambda pid: (-counts.get(pid, 0), pid))

    def recommend(self, user_id: str, top_n: int, at: pd.Timestamp,
                  policy_seed: int) -> list[RecommendationItem]:
        self.service.at = at
        self.service.rng = np.random.default_rng(policy_seed)
        if self.strategy == 'full_pipeline':
            return self.service.recommend(user_id, top_n).recommendations
        if self.strategy == 'popularity':
            ids = []
            for pid in self.popular:
                if self.service.table.created[self.service.table.id_to_index[pid]] <= at.value:
                    ids.append(pid)
                    if len(ids) == top_n:
                        break
        else:
            features = self.store.get_features(user_id)
            context = self.service.context(user_id, features.recent_clicks)
            ids = self.service.candidate.retrieve(context, self.service.cfg['recommend']['candidate_k'],
                                                  self.service.cfg['recommend']['exclude_purchased'])[:top_n]
        self.store.record_exposures(user_id, ids)
        return [RecommendationItem(product_id=pid, score=float(top_n - rank),
                                   reason=self.strategy) for rank, pid in enumerate(ids)]


class UserOutcome(TypedDict):
    user_id: str
    impressions: int
    clicks: int
    purchases: int
    explorations: int


def create_policies(cfg: dict, data: dict, clock: list[float]) -> tuple[dict, dict]:
    from src.recommendation.feature_store import RecommendationFeatureStore
    from src.recommendation.reranking import Reranker
    from src.recommendation.service import create_service
    spec = cfg['serving']['ab_test']
    names = {'control': spec['control'], 'treatment': spec['treatment']}
    if names['control'] not in ('popularity', 'two_tower') or names['treatment'] != 'full_pipeline':
        raise ValueError('control must be popularity/two_tower; treatment must be full_pipeline')
    base_cfg = copy.deepcopy(cfg)
    base_cfg['recommend']['enable_reranking'] = True
    base_cfg['recommend']['record_exposures'] = True
    base = create_service(base_cfg, RecommendationFeatureStore(cfg, data['products']))
    if base is None:
        raise ValueError('compatible Two Tower/FAISS/DeepFM/session bundles required; regenerate first')
    policies = {}
    for arm, strategy in names.items():
        service = copy.copy(base)
        service.cfg = copy.deepcopy(base_cfg)
        service.store = UserIsolatedStore(service.cfg, data['products'], clock=lambda: clock[0])
        service.reranker = Reranker(service.cfg, data['products'])
        service._lock = threading.RLock()
        service.last_diagnostics = {}
        policies[arm] = ModelPolicy(service, strategy, data['train'])
    # service loaders have already checked data/config and every bundle's hashes.
    from src.recommendation.train_two_tower import load_bundle
    from src.recommendation.train_deepfm import load_ranking
    from src.recommendation.train_session import load_session
    path = Path(cfg['recommend'].get('candidate_bundle', Path(cfg['paths']['model_dir']) / 'v1.0'))
    _, _, table, candidate = load_bundle(path, data, cfg)
    _, _, ranking = load_ranking(cfg, data)
    _, session = load_session(cfg, data, table, candidate)
    return policies, {'candidate': candidate, 'ranking': ranking, 'session': session}


def outcome_probabilities(cfg: dict, user: dict, product: dict, rank: int) -> tuple[float, float]:
    """Same persona/category/price model for both arms; purchase implies click."""
    spec = cfg['serving']['ab_test']['outcome']
    persona = cfg['simulator']['personas'][user['persona']]
    categories = list(cfg['simulator']['taxonomy'])
    affinity = persona['category_preferences'][categories.index(product['category_l1'])] * len(categories)
    low, high = cfg['simulator']['category_price_ranges'][product['category_l1']]
    price = float(np.clip((product['price'] - low) / (high - low), 0, 1))
    appeal = affinity ** spec['category_weight'] * np.exp(-spec['price_penalty'] * persona['price_sensitivity'] * price)
    click = spec['click_base'] * appeal / (rank + 1) ** spec['position_decay']
    purchase_given_click = persona['cvr'] * spec['conversion_multiplier'] * appeal
    return float(np.clip(click, 0, 1)), float(np.clip(purchase_given_click, 0, 1))


def summarize(rows: Sequence[Mapping[str, Any]], policy: Any) -> dict:
    sums = {key: sum(row[key] for row in rows) for key in ('impressions', 'clicks', 'purchases', 'explorations')}
    return dict(users=len(rows), **sums,
                ctr=sums['clicks'] / sums['impressions'] if sums['impressions'] else None,
                cvr=sums['purchases'] / sums['impressions'] if sums['impressions'] else None,
                purchase_given_click=sums['purchases'] / sums['clicks'] if sums['clicks'] else None,
                exploration_rate=sums['explorations'] / sums['impressions'] if sums['impressions'] else None,
                users_clicked=sum(row['clicks'] > 0 for row in rows),
                users_purchased=sum(row['purchases'] > 0 for row in rows),
                arm_statistics=(policy.store.experiment_statistics() if hasattr(policy.store, 'experiment_statistics')
                                else policy.store.arm_statistics()),
                unattributed_feedback=policy.store.unattributed_feedback)


def simulate(cfg: dict, data: dict, policies: dict, clock: list[float]) -> dict:
    if policies['control'].store is policies['treatment'].store:
        raise ValueError('control and treatment must have independent stores')
    spec = cfg['serving']['ab_test']
    if int(spec['days']) < 1 or not 1 <= int(spec['top_n']) <= 100:
        raise ValueError('days must be positive; top_n must be 1..100')
    if any(not np.isfinite(v) or v < 0 for v in spec['outcome'].values()):
        raise ValueError('outcome parameters must be finite and nonnegative')
    users = data['users'].set_index('user_id').to_dict('index')
    products = data['products'].set_index('product_id').to_dict('index')
    n = int(spec['users_per_group'])
    if cfg['scale'] == 'dev':
        fraction = float(spec['dev_population_fraction'])
        if not 0 < fraction <= 1:
            raise ValueError('dev population fraction must be in (0,1]')
        n = min(n, int(len(users) * fraction / 2))
    assignment = assign_users(list(users), cfg['seed'], n)
    rows: dict[str, dict[str, UserOutcome]] = {arm: {uid: dict(user_id=uid, impressions=0, clicks=0, purchases=0, explorations=0)
                  for uid in members} for arm, members in assignment.items()}
    start = pd.Timestamp(cfg['simulator']['reference_time'])
    for day in range(int(spec['days'])):
        clock[0] = float(day * 86400)
        at = start + pd.Timedelta(days=day)
        for arm in ('control', 'treatment'):
            for uid in assignment[arm]:
                # Hash-keyed independent streams survive iteration/arm-order changes.
                rng = np.random.default_rng(stream_seed(cfg['seed'], 'outcome', uid, day))
                items = policies[arm].recommend(uid, spec['top_n'], at,
                                                stream_seed(cfg['seed'], 'policy', uid, day))
                ids = [item.product_id for item in items]
                if len(ids) != len(set(ids)) or len(ids) > spec['top_n']:
                    raise ValueError('policy returned duplicate/excess items')
                row = rows[arm][uid]
                for rank, item in enumerate(items):
                    product = products[item.product_id]
                    if pd.Timestamp(product['created_at']) > at:
                        raise ValueError('policy exposed a future product')
                    pc, pp = outcome_probabilities(cfg, users[uid], product, rank)
                    click_draw, purchase_draw = rng.random(2)
                    click = click_draw < pc
                    purchase = click and purchase_draw < pp
                    row['impressions'] += 1
                    row['explorations'] += int(item.is_exploration)
                    row['clicks'] += int(click)
                    row['purchases'] += int(purchase)
                    for happened, kind in ((click, 'view'), (purchase, 'purchase')):
                        if happened:
                            event = FeedbackRequest(event_id=f'ab:{uid}:{day}:{rank}:{kind}',
                                user_id=uid, product_id=item.product_id, event_type=cast(Literal['view', 'purchase'], kind),
                                session_id=f'ab:{uid}:{day}', category=product['category_l3'])
                            policies[arm].store.append_event(event)
                            policies[arm].store.update_reward(event)
        print(f'AB day={day + 1}/{spec["days"]} users_per_group={n}', flush=True)
    user_rows = {arm: list(values.values()) for arm, values in rows.items()}
    arms = {arm: summarize(values, policies[arm]) for arm, values in user_rows.items()}
    if any(value['unattributed_feedback'] for value in arms.values()):
        raise ValueError('simulation feedback must be attributable to its arm exposure')
    risks = {name: binary_comparison(arms['control'][key], n, arms['treatment'][key], n)
             for name, key in [('any_click', 'users_clicked'), ('any_purchase', 'users_purchased')]}
    return dict(version=VERSION, status='PASS', acceptance='UNMEASURED', scale=cfg['scale'], seed=cfg['seed'],
                simulated_start=start.isoformat(), days=spec['days'], top_n=spec['top_n'],
                strategies={arm: spec[arm] for arm in assignment}, assignment=assignment,
                assignment_sha256=fingerprint(assignment), arms=arms, user_outcomes=user_rows,
                inference=dict(experimental_unit='randomized user; repeated exposures clustered within user',
                    independent_user_risks=risks,
                    ctr=clustered_rate(user_rows['control'], user_rows['treatment'], 'clicks', 'impressions'),
                    cvr=clustered_rate(user_rows['control'], user_rows['treatment'], 'purchases', 'impressions')),
                denominators=dict(ctr='clicks / impressions', cvr='purchases / impressions',
                    purchase_given_click='purchases / clicks', exploration_rate='marked exploration slots / impressions',
                    independent_user_risks='users with >=1 outcome / randomized users'),
                outcome_model=dict(parameters=spec['outcome'],
                    semantics='persona L1 affinity, normalized price sensitivity, position decay; identical formula in both arms; purchase conditional on click',
                    latent_preferences_used=False),
                isolation='immutable loaded models shared; separate arm and per-user adaptive stores/config/RNG/locks; common virtual clock; hash-keyed user/day outcome streams',
                limitations=['synthetic randomized simulation; no guarantee of positive or significant lift',
                    'static catalog and train+valid history; no test outcomes read',
                    'MAB exposure/feedback uses B5 in-memory adapter; live Redis attribution is verified separately',
                    'per-user adaptive bandits preserve independent user clusters; this is not a shared cross-user live-bandit experiment',
                    'dev result is not full acceptance'])


def run(cfg: dict, output: Path) -> dict:
    import torch
    from src.common.seed import set_seed
    from src.recommendation.datasets import read_data
    if os.getenv('PYTHONHASHSEED') != str(cfg['seed']):
        raise ValueError('launch with configured PYTHONHASHSEED before Python starts')
    set_seed(cfg['seed'])
    data = read_data(cfg['paths']['data_dir'], 'valid')
    clock = [0.]
    policies, bundles = create_policies(cfg, data, clock)
    with torch.inference_mode():
        report = simulate(cfg, data, policies, clock)
    sources = ['src/evaluation/ab_test.py', 'src/evaluation/ab_statistics.py',
               'src/recommendation/service.py', 'src/recommendation/recommender.py',
               'src/recommendation/reranking.py', 'src/recommendation/mab.py',
               'src/recommendation/feature_store.py', 'src/recommendation/scoring.py',
               'src/recommendation/session.py']
    report['identity'] = dict(data_fingerprint=data['manifest']['generation_fingerprint'],
        data_hashes=data['manifest']['file_hashes'], config_fingerprint=fingerprint(cfg),
        bundle_metadata=bundles, source_hashes={name: file_hash(Path(name)) for name in sources})
    report['run_id'] = fingerprint(dict(identity=report['identity'], assignment=report['assignment_sha256'],
                                        version=VERSION))
    report['environment'] = dict(python=platform.python_version(), platform=platform.platform(),
        torch=torch.__version__, numpy=np.__version__, device='cpu', threads=torch.get_num_threads(),
        pythonhashseed=os.getenv('PYTHONHASHSEED'),
        determinism='seed42 CPU; floating-point/model bytes may differ across OS/Python versions')
    write_json(output, report)
    print(json.dumps(dict(output=str(output), arms={arm: {k: v for k, v in value.items() if k != 'arm_statistics'}
        for arm, value in report['arms'].items()}, inference=report['inference']), ensure_ascii=False, indent=2))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    cfg = load_config()
    run(cfg, args.output or Path(cfg['paths']['results_dir']) / 'ab_test.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

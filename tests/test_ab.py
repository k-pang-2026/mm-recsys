from __future__ import annotations

import pandas as pd
import pytest

from src.common.config import load_config
from src.common.schemas import RecommendationItem
from src.evaluation.ab_statistics import binary_comparison, clustered_rate
from src.evaluation.ab_test import (assign_users, create_policies, outcome_probabilities,
                                    simulate, stream_seed, UserIsolatedStore)
from src.recommendation.feature_store import RecommendationFeatureStore


def fixture():
    cfg = load_config()
    cfg['serving']['ab_test'].update(users_per_group=10, dev_population_fraction=1., days=3, top_n=2)
    names = list(cfg['simulator']['personas'])
    data = dict(users=pd.DataFrame([dict(user_id=f'U{i}', persona=names[i % len(names)]) for i in range(20)]),
                products=pd.DataFrame([
                    dict(product_id='P1', category_l1='tops', category_l3='shirt', price=20000,
                         created_at=pd.Timestamp('2025-01-01', tz='UTC')),
                    dict(product_id='P2', category_l1='bottoms', category_l3='jeans', price=80000,
                         created_at=pd.Timestamp('2025-01-01', tz='UTC'))]))
    return cfg, data


class FixedPolicy:
    def __init__(self, cfg, products, clock, exploration=False):
        self.store = RecommendationFeatureStore(cfg, products, clock=lambda: clock[0])
        self.exploration = exploration

    def recommend(self, uid, top_n, at, policy_seed):
        self.store.record_exposures(uid, ['P1', 'P2'])
        return [RecommendationItem(product_id=p, score=1., reason='fixed',
                                   is_exploration=self.exploration) for p in ['P1', 'P2']]


def run_fixture(cfg, data, exploration=True):
    clock = [0.]
    policies = {arm: FixedPolicy(cfg, data['products'], clock, exploration and arm == 'treatment')
                for arm in ('control', 'treatment')}
    return simulate(cfg, data, policies, clock), policies


def test_assignment_is_seeded_disjoint_balanced_order_independent():
    users = [str(i) for i in range(20)]
    value = assign_users(users, 42, 7)
    assert value == assign_users(users[::-1], 42, 7)
    assert len(value['control']) == len(value['treatment']) == 7
    assert not set(value['control']) & set(value['treatment'])
    assert value != assign_users(users, 43, 7)
    with pytest.raises(ValueError):
        assign_users(users, 42, 11)
    with pytest.raises(ValueError):
        assign_users(['same'] * 10, 42, 2)
    assert stream_seed(42, 'outcome', 'U1', 1) != stream_seed(42, 'policy', 'U1', 1)


def test_known_binary_equal_and_different_rates():
    equal = binary_comparison(100, 1000, 100, 1000)
    assert equal['z_p_value'] == equal['chi_square_p_value'] == 1.
    assert equal['difference_ci95'][0] < 0 < equal['difference_ci95'][1]
    different = binary_comparison(100, 1000, 250, 1000)
    assert different['z_p_value'] < 1e-10
    assert different['z_p_value'] == pytest.approx(different['chi_square_p_value'])
    assert different['difference_ci95'][0] > 0
    assert different['relative_lift'] == pytest.approx(1.5)
    reversed_ = binary_comparison(250, 1000, 100, 1000)
    assert reversed_['z_p_value'] == different['z_p_value']
    assert reversed_['difference_ci95'][1] < 0


@pytest.mark.parametrize('count', [0, 10])
def test_boundary_counts_and_low_frequency_are_explicit(count):
    value = binary_comparison(count, 10, count, 10)
    assert value['z_p_value'] == value['chi_square_p_value'] == value['fisher_p_value'] == 1.
    assert not value['asymptotic_reliable']
    assert binary_comparison(0, 10, 1, 10)['low_expected_counts']
    with pytest.raises(ValueError):
        binary_comparison(11, 10, 1, 10)


def test_clustered_rates_do_not_treat_repeat_exposures_as_new_users():
    control = [dict(clicks=x, impressions=10) for x in (0, 2, 4, 6)]
    treatment = [dict(clicks=x, impressions=10) for x in (2, 4, 6, 8)]
    value = clustered_rate(control, treatment, 'clicks', 'impressions')
    scaled = [{key: v * 100 for key, v in r.items()} for r in control]
    scaled_t = [{key: v * 100 for key, v in r.items()} for r in treatment]
    assert value == clustered_rate(scaled, scaled_t, 'clicks', 'impressions')
    assert value['difference'] == pytest.approx(.2)
    empty = [dict(clicks=0, impressions=0)] * 4
    assert clustered_rate(empty, treatment, 'clicks', 'impressions')['status'] == 'UNMEASURED'
    assert clustered_rate(empty, treatment, 'clicks', 'impressions')['relative_lift'] is None


def test_simulation_is_reproducible_causal_and_arm_isolated():
    cfg, data = fixture()
    first, policies = run_fixture(cfg, data)
    second, _ = run_fixture(cfg, data)
    assert first == second
    assert policies['control'].store is not policies['treatment'].store
    for arm, rows in first['user_outcomes'].items():
        assert first['arms'][arm]['impressions'] == 10 * 3 * 2
        assert first['arms'][arm]['unattributed_feedback'] == 0
        assert all(r['purchases'] <= r['clicks'] <= r['impressions'] for r in rows)
        assert set(policies[arm].store._sessions) <= set(first['assignment'][arm])
        assert sum(v['exposures'] for v in first['arms'][arm]['arm_statistics'].values()) == 60
    assert first['arms']['control']['exploration_rate'] == 0
    assert first['arms']['treatment']['exploration_rate'] == 1
    # Exploration markers never directly change generated outcomes.
    unmarked, _ = run_fixture(cfg, data, exploration=False)
    for arm in first['arms']:
        assert first['arms'][arm]['clicks'] == unmarked['arms'][arm]['clicks']
        assert first['arms'][arm]['purchases'] == unmarked['arms'][arm]['purchases']


def test_no_hardcoded_treatment_uplift_and_price_response():
    cfg, data = fixture()
    user = data['users'].iloc[2].to_dict()
    product = data['products'].iloc[0].to_dict()
    cheap = outcome_probabilities(cfg, user, product, 0)
    expensive = outcome_probabilities(cfg, user, dict(product, price=140000), 0)
    assert cheap[0] > expensive[0] and cheap[1] > expensive[1]
    assert outcome_probabilities(cfg, user, product, 9)[0] < cheap[0]
    cfg['serving']['ab_test']['outcome']['click_base'] = 0.
    report, _ = run_fixture(cfg, data)
    assert all(row['clicks'] == row['purchases'] == 0 for row in report['arms'].values())
    assert report['inference']['cvr']['relative_lift'] is None


def test_invalid_state_or_future_inventory_is_rejected():
    cfg, data = fixture()
    clock = [0.]
    policy = FixedPolicy(cfg, data['products'], clock)
    with pytest.raises(ValueError, match='independent stores'):
        simulate(cfg, data, dict(control=policy, treatment=policy), clock)
    cfg['serving']['ab_test']['outcome']['click_base'] = float('nan')
    with pytest.raises(ValueError, match='finite'):
        run_fixture(cfg, data)
    cfg['serving']['ab_test']['outcome']['click_base'] = .3
    data['products'].loc[0, 'created_at'] = pd.Timestamp('2030-01-01', tz='UTC')
    with pytest.raises(ValueError, match='future product'):
        run_fixture(cfg, data)


def test_model_policy_factory_uses_separate_mutable_state(monkeypatch):
    from types import SimpleNamespace
    import src.recommendation.service as service
    import src.recommendation.train_two_tower as candidate
    import src.recommendation.train_deepfm as ranking
    import src.recommendation.train_session as session
    cfg, data = fixture()
    # No model mock is used in the actual CLI run; this fixture isolates ownership.
    data['train'] = pd.DataFrame([dict(product_id='P1')])
    base = SimpleNamespace(table=SimpleNamespace(ids=['PAD', 'P1', 'P2']))
    monkeypatch.setattr(service, 'create_service', lambda *args: base)
    monkeypatch.setattr(candidate, 'load_bundle', lambda *args: (None, None, None, {'hash': 'candidate'}))
    monkeypatch.setattr(ranking, 'load_ranking', lambda *args: (None, None, {'hash': 'ranking'}))
    monkeypatch.setattr(session, 'load_session', lambda *args: (None, {'hash': 'session'}))
    policies, _ = create_policies(cfg, data, [0.])
    a, b = policies['control'].service, policies['treatment'].service
    assert a.store is not b.store and a.cfg is not b.cfg and a.reranker is not b.reranker
    a.store.record_exposures('U0', ['P1'])
    assert b.store.arm_statistics() == {}
    a.cfg['recommend']['mab']['epsilon'] = 0.
    assert b.cfg['recommend']['mab']['epsilon'] == .1
    cfg['serving']['ab_test']['control'] = 'invented'
    with pytest.raises(ValueError, match='control must'):
        create_policies(cfg, data, [0.])


def test_two_tower_control_and_full_pipeline_use_real_fixture_bundles(tmp_path, monkeypatch):
    from src.common.schemas import FeedbackRequest
    from src.recommendation.testing import service_fixture
    monkeypatch.delenv('RECOMMEND_MODEL_DIR', raising=False)
    cfg, data = service_fixture(tmp_path)
    cfg['serving']['ab_test']['control'] = 'two_tower'
    policies, identity = create_policies(cfg, data, [0.])
    at = pd.Timestamp(cfg['simulator']['reference_time'])
    import torch
    with torch.inference_mode():
        control = policies['control'].recommend('u', 5, at, 42)
        treatment = policies['treatment'].recommend('u', 5, at, 42)
    assert len(control) == len(treatment) == 5
    assert not any(item.is_exploration for item in control)
    assert sum(item.is_exploration for item in treatment) == 2
    event = FeedbackRequest(event_id='purchase', user_id='u', product_id=treatment[0].product_id,
                            event_type='purchase')
    policies['treatment'].store.update_reward(event)
    assert sum(value['reward'] for value in policies['control'].store.arm_statistics().values()) == 0
    assert sum(value['reward'] for value in policies['treatment'].store.arm_statistics().values()) == 1
    assert identity['session']['candidate_sha256'] == identity['candidate']['hashes']['two_tower.pt']


def test_adaptive_learning_does_not_cross_user_clusters():
    from src.common.schemas import FeedbackRequest
    cfg, data = fixture()
    store = UserIsolatedStore(cfg, data['products'], lambda: 0.)
    store.record_exposures('U1', ['P1'])
    store.update_reward(FeedbackRequest(event_id='reward', user_id='U1', product_id='P1', event_type='purchase'))
    assert store.arm_statistics()['P1']['reward'] == 1.
    store.get_features('U2')
    assert store.arm_statistics() == {}
    store.record_exposures('U2', ['P1'])
    assert store.arm_statistics()['P1']['reward'] == 0.
    assert store.users['U1'] is not store.users['U2']
    assert sum(v['exposures'] for v in store.experiment_statistics().values()) == 2

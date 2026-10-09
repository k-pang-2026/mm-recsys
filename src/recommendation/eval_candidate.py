"""Fixed-origin, unique future item truth, macro-user Recall over exactly top300."""
from __future__ import annotations

import argparse
import platform
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from src.common.artifacts import file_hash, fingerprint, write_json
from src.common.config import load_config
from src.recommendation.baselines import Baselines
from src.recommendation.candidate import ExactCandidate, FaissCandidate, dot_scores, top_indices, flat_reference
from src.recommendation.datasets import context_for, cutoff_for, read_data
from src.recommendation.features import FeatureEncoder, ItemTable


class Evaluation:
    def __init__(self, data: dict, encoder: FeatureEncoder, table: ItemTable, cfg: dict, split: str = 'valid'):
        evaluation = cfg['recommend']['evaluation']
        if evaluation['k'] != 300 or evaluation['aggregation'] != 'macro_user' or evaluation['cutoff_policy'] != 'fixed_origin':
            raise ValueError('frozen evaluation requires fixed_origin macro_user Recall@300')
        self.cfg, self.table, self.split, self.cutoff = cfg, table, split, cutoff_for(data, split)
        self.eligible = table.eligible(self.cutoff)
        history = data['train'] if split == 'valid' else pd.concat([data['train'], data['valid']], ignore_index=True)
        groups = {uid: group for uid, group in history.groupby('user_id', sort=False)}
        user_rows = data['users'].set_index('user_id').to_dict('index')
        future = data[split]
        truth = future[future.event_type.isin(evaluation['target_events']) & future.product_id.notna()]
        self.truth = {str(uid): set(group.product_id.astype(str)) for uid, group in truth.groupby('user_id', sort=True)}
        self.user_ids = sorted(self.truth)
        self.empty_users = len(set(data['users'].user_id.astype(str)) | set(future.user_id.astype(str))) - len(self.user_ids)
        empty = history.iloc[:0]
        self.contexts = [context_for(groups.get(uid, empty), user_rows.get(uid), encoder, table, self.cutoff,
                                     cfg['recommend']['candidate']['history_n']) for uid in self.user_ids]
        # Popularity excludes the cutoff timestamp and never consumes valid/test interactions.
        train = data['train'][data['train'].timestamp < self.cutoff]
        self.baselines = Baselines(train, table, cfg['recommend']['candidate']['positive_weights'], cfg['recommend']['baselines'])
        self.data_fingerprint = data['manifest']['generation_fingerprint']

    def measure(self, ranked: list[list[str]]) -> dict:
        if len(ranked) != len(self.user_ids):
            raise ValueError('ranked/user mapping mismatch')
        recalls, sizes, bounds = [], [], []
        cohorts: dict[str, list[float]] = defaultdict(list)
        eligible_ids = set(self.table.public_ids(self.eligible))
        unavailable = rare = new = repeated = 0
        diagnostics = self.cfg['recommend']['diagnostics']
        for uid, context, recommendation in zip(self.user_ids, self.contexts, ranked):
            truth = self.truth[uid]
            # Metric always truncates; overretrieval never changes Recall@300.
            top = recommendation[:300]
            if len(top) != len(set(top)) or any(pid not in eligible_ids for pid in top):
                raise ValueError('duplicate/ineligible candidates')
            if len(top) != min(300, len(self.eligible)):
                raise ValueError('candidate count must equal min(300, eligible catalog)')
            recall = len(set(top) & truth) / len(truth)
            recalls.append(recall); sizes.append(len(top)); bounds.append(min(300, len(truth)) / len(truth))
            n_unavailable = len(truth - eligible_ids)
            n_rare = int(sum(self.baselines.counts[self.table.id_to_index[pid]] <= diagnostics['rare_max_train_events'] for pid in truth))
            n_new = int(sum(self.table.created[self.table.id_to_index[pid]] >= self.cutoff.value - pd.Timedelta(days=self.cfg['recommend']['new_item_days']).value for pid in truth))
            n_repeat = sum(self.table.id_to_index[pid] in context.purchased for pid in truth)
            unavailable += n_unavailable; rare += n_rare; new += n_new; repeated += n_repeat
            cohorts['all'].append(recall)
            cohorts['cold' if context.history_count <= diagnostics['cold_max_history'] else 'warm'].append(recall)
            if context.history_count == 0: cohorts['no_history'].append(recall)
            if n_rare: cohorts['rare_target'].append(recall)
            if n_new: cohorts['new_target'].append(recall)
            if n_unavailable: cohorts['unavailable_target'].append(recall)
            if n_repeat: cohorts['repeat_purchase'].append(recall)
        summary = {name: {'users': len(cohorts[name]), 'recall_at_300': float(np.mean(cohorts[name])) if cohorts[name] else None}
                   for name in ['all', 'cold', 'warm', 'no_history', 'rare_target', 'new_target', 'unavailable_target', 'repeat_purchase']}
        return dict(recall_at_300=float(np.mean(recalls)) if recalls else None,
                    macro_users=len(recalls), empty_target_users=self.empty_users,
                    average_truth_size=float(np.mean([len(t) for t in self.truth.values()])) if recalls else 0,
                    candidate_count_min=min(sizes, default=0), candidate_count_max=max(sizes, default=0),
                    eligible_catalog=len(self.eligible), unavailable_truth_items=unavailable,
                    rare_truth_items=rare, new_truth_items=new, repeated_purchase_truth_items=repeated,
                    average_recall_upper_bound=float(np.mean(bounds)) if bounds else None, cohorts=summary)

    def model(self, model) -> dict:
        batch_size = self.cfg['recommend']['candidate']['batch_size']
        reference = ExactCandidate(model, self.table, self.eligible, batch_size)
        ranked = []
        for start in range(0, len(self.contexts), batch_size):
            vectors = reference.user_vectors(self.contexts[start:start + batch_size])
            scores = dot_scores(vectors, reference.vectors)
            ranked.extend(self.table.public_ids(top_indices(row, self.eligible)) for row in scores)
        return self.measure(ranked)

    def baseline_metrics(self) -> dict:
        popularity = self.table.public_ids(top_indices(self.baselines.popularity[self.eligible], self.eligible))
        history = [self.table.public_ids(top_indices(self.baselines.history_scores(c, self.eligible), self.eligible)) for c in self.contexts]
        return {'train_popularity': self.measure([popularity] * len(self.contexts)), 'observed_history_profile': self.measure(history)}

    def ann_metrics(self, model, index) -> dict:
        from src.recommendation.runtime import configure_inference
        configure_inference(self.cfg['recommend']['candidate'], with_faiss=True)
        import faiss
        batch_size = self.cfg['recommend']['candidate']['batch_size']
        reference, exact = flat_reference(model, self.table, self.eligible, batch_size)
        from src.recommendation.index import stored_vectors
        persisted_vectors = stored_vectors(index)[self.eligible - 1]
        if not np.allclose(persisted_vectors, reference.vectors, rtol=1e-5, atol=1e-6):
            raise ValueError('exact/ANN vectors differ from loaded checkpoint')
        # Use persisted vectors for exact agreement, including CPU batching roundoff.
        exact.reset()
        exact.add(np.ascontiguousarray(persisted_vectors))
        ann = FaissCandidate(model, self.table, self.eligible, index)
        exact_ranked, ann_ranked, agreement = [], [], []
        for start in range(0, len(self.contexts), batch_size):
            vectors = reference.user_vectors(self.contexts[start:start + batch_size])
            scores, labels = exact.search(vectors, min(300, len(self.eligible)))
            for values, positions in zip(scores, labels):
                rows = self.eligible[positions[positions >= 0]]
                values = values[positions >= 0]
                exact_ranked.append(self.table.public_ids(rows[np.lexsort((rows, -values))]))
            ann_ranked.extend(ann.search(vectors))
        for one, two in zip(exact_ranked, ann_ranked):
            agreement.append(len(set(one) & set(two)) / len(one) if one else 1.0)
        return dict(exact_flat_ip=self.measure(exact_ranked), ann_two_tower=self.measure(ann_ranked),
                    ann_agreement_at_300=float(np.mean(agreement)) if agreement else None,
                    agreement_denominator='exact IndexFlatIP top300 IDs, not future truth',
                    agreement_users=len(agreement), boundary_ties='FAISS top-k tie selection; public-ID order within returned ties')

    def contract(self) -> dict:
        return dict(version='fixed-origin-v1', split=self.split, cutoff=self.cutoff.isoformat(), k=300,
                    truth='unique cart/purchase product IDs in evaluation interval; unavailable retained',
                    catalog='all products registered <= cutoff', history='events strictly < cutoff; frozen',
                    aggregation='macro_user; all nonempty-target users', empty_target_users='reported; excluded from mean',
                    exclude_purchased=False, model='metadata-only Two Tower; no item-ID residual',
                    data_fingerprint=self.data_fingerprint, evaluation_fingerprint=fingerprint(self.cfg['recommend']['evaluation']))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--split', choices=['valid', 'test'], required=True)
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--ann', action='store_true', help='compare persisted HNSW against identical-vector IndexFlatIP')
    args = parser.parse_args()
    cfg = load_config()
    import torch
    from src.recommendation.runtime import configure_inference
    configure_inference(cfg['recommend']['candidate'])
    from src.recommendation.train_two_tower import load_bundle
    bundle = args.bundle or Path(cfg['paths']['model_dir']) / 'v1.0'
    data = read_data(cfg['paths']['data_dir'], args.split)
    model, encoder, table, meta = load_bundle(bundle, data, cfg)
    evaluation = Evaluation(data, encoder, table, cfg, args.split)
    report = dict(status='PASS', acceptance='UNMEASURED', scale=cfg['scale'], contract=evaluation.contract(),
                  exact_two_tower=evaluation.model(model), baselines=evaluation.baseline_metrics(),
                  model_sha256=file_hash(bundle / 'two_tower.pt'), bundle_meta=meta)
    if args.ann:
        from src.recommendation.index import load_index
        index, manifest = load_index(bundle, table, meta)
        report.update(evaluation.ann_metrics(model, index))
        report['index_manifest'] = manifest
    report['data_counts'] = data['manifest']['counts']
    report['environment'] = dict(python=platform.python_version(), torch=torch.__version__, numpy=np.__version__,
                               platform=platform.platform(), threads=torch.get_num_threads(), device='cpu')
    output = args.output or Path(cfg['paths']['results_dir']) / f'candidate_{cfg["scale"]}_{args.split}.json'
    write_json(output, report)
    print(f'{args.split}: exact Recall@300={report["exact_two_tower"]["recall_at_300"]:.6f}; output={output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

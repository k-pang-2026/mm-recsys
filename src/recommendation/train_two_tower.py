"""CPU-first reproducible sampled-softmax training, valid-selected checkpoint and bundle."""
from __future__ import annotations

import argparse
import copy
import json
import os
import platform
import time
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

from src.common.artifacts import file_hash, fingerprint, write_json
from src.common.config import load_config
from src.common.seed import set_seed
from src.recommendation.datasets import TrainingDataset, cutoff_for, read_data
from src.recommendation.eval_candidate import Evaluation
from src.recommendation.features import FeatureEncoder
from src.recommendation.two_tower import TwoTower, weighted_loss


def seed_worker(worker_id: int) -> None:
    # Independent from negative sampling's numpy Generator.
    import random
    seed = torch.initial_seed() % 2**32
    np.random.seed(seed); random.seed(seed)


def tiny_fit(model: TwoTower, dataset: TrainingDataset, cfg: dict) -> dict:
    """Fixed train-only fixture tests the complete user/item/optimizer pathway."""
    selected, signatures = [], set()
    for index in range(len(dataset)):
        history = dataset.history[index]
        positive = int(dataset.items[index, 0])
        if positive not in history.tolist():
            continue
        signature = tuple(history.tolist())
        if signature in signatures:
            continue
        signatures.add(signature); selected.append(index)
        if len(selected) == 16:
            break
    if len(selected) < 2:
        raise ValueError('tiny train-fit requires >=2 distinct observed histories with repeated positives')
    batch = {key: torch.stack([dataset[i][key] for i in selected]) for key in dataset[0]}
    fixture = copy.deepcopy(model).train()
    spec = cfg['recommend']['candidate']
    optimizer = torch.optim.AdamW(fixture.parameters(), lr=spec['tiny_fit_learning_rate'], weight_decay=0)
    with torch.no_grad():
        initial_logits, _, _ = fixture(batch)
        initial_loss = float(weighted_loss(initial_logits, batch['weights']))
        initial_accuracy = float((initial_logits.argmax(1) == 0).float().mean())
    gradient_steps = 0
    for _ in range(spec['tiny_fit_steps']):
        optimizer.zero_grad(set_to_none=True)
        logits, _, _ = fixture(batch)
        loss = weighted_loss(logits, batch['weights'])
        loss.backward()
        if not torch.isfinite(loss):
            raise ValueError('nonfinite tiny loss')
        gradient_steps += int(any(p.grad is not None and bool(p.grad.abs().sum() > 0) for p in fixture.parameters()))
        optimizer.step()
    with torch.no_grad():
        final_logits, _, _ = fixture(batch)
        final_loss = float(weighted_loss(final_logits, batch['weights']))
        final_accuracy = float((final_logits.argmax(1) == 0).float().mean())
        margin = float((final_logits[:, 0] - final_logits[:, 1:].mean(1)).mean()) * fixture.temperature
    passed = final_loss < initial_loss * 0.5 and final_accuracy >= 0.95 and margin > 0 and gradient_steps == spec['tiny_fit_steps']
    result = dict(status='PASS' if passed else 'FAIL', scope='train-only debugging; not retrieval quality',
                  sample_count=len(selected), event_ids=[dataset.event_ids[i] for i in selected],
                  fixture_fingerprint=fingerprint({k: v.tolist() for k, v in batch.items()}),
                  initial_loss=initial_loss, final_loss=final_loss, initial_accuracy=initial_accuracy,
                  final_accuracy=final_accuracy, final_cosine_margin=margin, gradient_steps=gradient_steps,
                  fixed_random_negatives=4)
    if not passed:
        raise ValueError(f'tiny train-fit failed: {result}')
    return result


def bundle_contract() -> dict:
    return dict(version='candidate-bundle-v1', directory='models[/full]/v1.0',
                files={'two_tower.pt': 'best valid-selected state_dict (weights_only load)',
                       'feature_vocab_scalers.json': 'train-only feature encoding including PAD=0/UNK=1',
                       'item_ids.json': 'canonical ordered public IDs, excludes PAD',
                       'meta.json': 'model/feature/config/data hashes, dimensions and cutoff'},
                planned_B3b={'item_index.faiss': 'HNSW inner-product, aligned with item_ids.json'},
                history_inputs=['observed product IDs before timestamp', 'age_group', 'gender',
                                'past purchase category/brand distribution and price'],
                item_inputs=['category_l1', 'category_l2', 'category_l3', 'brand', 'color', 'style', 'price'],
                persona=False, item_id_residual=False, normalized=True, metric='inner_product')


def save_bundle(path: Path, model: TwoTower, encoder: FeatureEncoder, table, cfg: dict,
                data: dict, best_epoch: int, recall: float) -> dict:
    path.mkdir(parents=True, exist_ok=True)
    state_path = path / 'two_tower.pt'
    temporary = path / '.two_tower.pt.tmp'
    torch.save(model.state_dict(), temporary); temporary.replace(state_path)
    write_json(path / 'feature_vocab_scalers.json', encoder.to_dict())
    write_json(path / 'item_ids.json', table.ids[1:])
    meta = dict(contract=bundle_contract(), scale=cfg['scale'], dim=cfg['recommend']['candidate']['dim'],
                model_version='v1.0', retrieval='exact; ANN index not built until B3b',
                best_epoch=best_epoch, best_valid_recall_at_300=recall,
                data_fingerprint=data['manifest']['generation_fingerprint'],
                catalog_sha256=data['manifest']['file_hashes']['products.parquet'],
                feature_fingerprint=encoder.digest, config_fingerprint=fingerprint(cfg['recommend']),
                training_spec=cfg['recommend']['candidate'],
                hashes={name: file_hash(path / name) for name in ['two_tower.pt', 'feature_vocab_scalers.json', 'item_ids.json']})
    write_json(path / 'meta.json', meta)
    return meta


def load_bundle(path: Path, data: dict, cfg: dict):
    meta = json.loads((path / 'meta.json').read_text())
    if meta['data_fingerprint'] != data['manifest']['generation_fingerprint'] or meta['catalog_sha256'] != data['manifest']['file_hashes']['products.parquet']:
        raise ValueError('stale bundle/data')
    if meta['config_fingerprint'] != fingerprint(cfg['recommend']):
        raise ValueError('bundle/recommend config mismatch')
    for name, digest in meta['hashes'].items():
        if file_hash(path / name) != digest:
            raise ValueError(f'bundle checksum mismatch: {name}')
    encoder = FeatureEncoder.from_dict(json.loads((path / 'feature_vocab_scalers.json').read_text()))
    if encoder.digest != meta['feature_fingerprint']:
        raise ValueError('feature fingerprint mismatch')
    table = encoder.item_table(data['products'])
    if json.loads((path / 'item_ids.json').read_text()) != table.ids[1:]:
        raise ValueError('bundle ID mapping mismatch')
    model = TwoTower(encoder, table, meta['training_spec'])
    model.load_state_dict(torch.load(path / 'two_tower.pt', map_location='cpu', weights_only=True))
    return model.eval(), encoder, table, meta


def train(cfg: dict, output: Path | None = None, bundle: Path | None = None) -> dict:
    started = time.perf_counter()
    set_seed(cfg['seed'])
    spec = cfg['recommend']['candidate']
    torch.set_num_threads(spec['threads'])
    data = read_data(cfg['paths']['data_dir'], 'valid')
    encoder = FeatureEncoder.fit(data['products'], data['users'], cutoff_for(data, 'valid'))
    table = encoder.item_table(data['products'])
    dataset = TrainingDataset(data['train'], data['users'], encoder, table, cfg)
    model = TwoTower(encoder, table, spec)
    tiny = tiny_fit(model, dataset, cfg)
    evaluation = Evaluation(data, encoder, table, cfg)
    baselines = evaluation.baseline_metrics()
    loader = DataLoader(dataset, batch_size=spec['batch_size'], shuffle=True, num_workers=spec['num_workers'],
                        generator=torch.Generator().manual_seed(cfg['seed'] + 2), worker_init_fn=seed_worker)
    optimizer = torch.optim.AdamW(model.parameters(), lr=spec['learning_rate'], weight_decay=spec['weight_decay'])
    best_recall, best_epoch, stale, epochs = -1.0, 0, 0, []
    best_state = None
    for epoch in range(1, spec['epochs'] + 1):
        epoch_start = time.perf_counter()
        model.train(); weighted_total = weight_total = margin_total = 0.0
        grad_total = user_norm = item_norm = 0.0
        updates = samples = 0
        before = {name: p.detach().clone() for name, p in model.named_parameters()}
        for batch in loader:
            optimizer.zero_grad(set_to_none=True)
            logits, users, items = model(batch)
            loss = weighted_loss(logits, batch['weights'])
            if not torch.isfinite(loss):
                raise ValueError('nonfinite training loss')
            loss.backward()
            grad = float(torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=10.0))
            if not np.isfinite(grad):
                raise ValueError('nonfinite gradient')
            optimizer.step(); updates += 1
            size = len(logits); samples += size
            weight = float(batch['weights'].sum())
            weighted_total += float(loss.detach()) * weight; weight_total += weight
            margin_total += float((logits[:, 0] - logits[:, 1:].mean(1)).detach().sum()) * model.temperature
            grad_total += grad
            user_norm += float(users.detach().norm(dim=-1).sum())
            item_norm += float(items.detach().norm(dim=-1).sum()) / items.shape[1]
        delta = float(sum((p.detach() - before[name]).square().sum() for name, p in model.named_parameters()).sqrt())
        metrics = evaluation.model(model)
        reference_contexts = evaluation.contexts[:min(128, len(evaluation.contexts))]
        from src.recommendation.candidate import ExactCandidate
        reference = ExactCandidate(model, table, evaluation.eligible, spec['batch_size'])
        probe_users = reference.user_vectors(reference_contexts)
        probe_items = reference.vectors
        diagnostic = dict(epoch=epoch, weighted_loss=weighted_total / weight_total,
                          cosine_positive_negative_margin=margin_total / samples,
                          mean_user_norm=user_norm / samples, mean_item_norm=item_norm / samples,
                          mean_gradient_norm=grad_total / updates, parameter_update_l2=delta,
                          optimizer_updates=updates, samples=samples,
                          user_dimension_std=float(probe_users.std(axis=0).mean()),
                          item_dimension_std=float(probe_items.std(axis=0).mean()),
                          user_mean_vector_norm=float(np.linalg.norm(probe_users.mean(axis=0))),
                          item_mean_vector_norm=float(np.linalg.norm(probe_items.mean(axis=0))),
                          valid=metrics, seconds=time.perf_counter() - epoch_start)
        epochs.append(diagnostic)
        recall = metrics['recall_at_300']
        if recall is None:
            raise ValueError('no valid truth users; cannot select checkpoint')
        print(f'epoch={epoch} loss={diagnostic["weighted_loss"]:.5f} valid_recall@300={recall:.6f} updates={updates}', flush=True)
        if recall > best_recall:
            best_recall, best_epoch, stale = recall, epoch, 0
            best_state = copy.deepcopy(model.state_dict())
        else:
            stale += 1
        if stale >= spec['patience']:
            break
    if best_state is None:
        raise ValueError('no best checkpoint')
    model.load_state_dict(best_state)
    bundle = bundle or Path(cfg['paths']['model_dir']) / 'v1.0'
    meta = save_bundle(bundle, model, encoder, table, cfg, data, best_epoch, best_recall)
    loaded, _, _, _ = load_bundle(bundle, data, cfg)
    reloaded = evaluation.model(loaded)
    if reloaded['recall_at_300'] != best_recall:
        raise ValueError('reloaded checkpoint differs from selected valid result')
    report = dict(status='PASS', acceptance='UNMEASURED', stage='B3a', scale=cfg['scale'], seed=cfg['seed'],
                  contract=evaluation.contract(), feature_contract=encoder.to_dict(), bundle_contract=bundle_contract(),
                  sampling=dataset.diagnostics, tiny_train_fit=tiny, baselines=baselines, epochs=epochs,
                  best_epoch=best_epoch, best_valid_exact=reloaded, checkpoint_reload='PASS', bundle=meta,
                  elapsed_seconds=time.perf_counter() - started,
                  environment=dict(python=platform.python_version(), torch=torch.__version__, numpy=np.__version__,
                                   platform=platform.platform(), cpu_count=os.cpu_count(), threads=torch.get_num_threads(),
                                   device='cpu', pythonhashseed=os.getenv('PYTHONHASHSEED'),
                                   determinism='seeded CPU run; cross-platform floating-point differences possible'),
                  full_test_quality='UNMEASURED', ann='UNMEASURED', latency='UNMEASURED')
    output = output or Path(cfg['paths']['results_dir']) / f'candidate_training_{cfg["scale"]}.json'
    write_json(output, report)
    print(f'best_epoch={best_epoch}; valid_recall@300={best_recall:.6f}; result={output}', flush=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    parser.add_argument('--bundle', type=Path)
    args = parser.parse_args()
    cfg = load_config()
    train(cfg, args.output, args.bundle)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

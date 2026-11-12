"""관측 데이터만으로 페르소나·구매 분포를 검증합니다. 학습 입력에는 사용하지 않습니다."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd

from src.common.artifacts import file_hash, write_json
from src.common.config import load_config
from src.common.console import emit_json, log, run_cli


def audit(cfg: dict, output: Path | None = None) -> dict:
    root = Path(cfg['paths']['data_dir'])
    manifest = json.loads((root / 'split_manifest.json').read_text())
    tables = {name: pd.read_parquet(root / f'{name}.parquet') for name in
              ('products', 'users', 'events', 'impressions')}
    products, users, events, impressions = (tables[name] for name in tables)
    integrity = {}
    for name, frame in tables.items():
        key = dict(products='product_id', users='user_id', events='event_id', impressions='impression_id')[name]
        integrity[name] = dict(rows=len(frame), duplicate_ids=int(frame[key].duplicated().sum()),
            nulls={c: int(v) for c, v in frame.isna().sum().items()},
            checksum_matches=file_hash(root / f'{name}.parquet') == manifest['file_hashes'][f'{name}.parquet'])
    references = dict(event_users=int((~events.user_id.isin(users.user_id)).sum()),
        event_products=int((events.product_id.notna() & ~events.product_id.isin(products.product_id)).sum()),
        impression_users=int((~impressions.user_id.isin(users.user_id)).sum()),
        impression_products=int((~impressions.product_id.isin(products.product_id)).sum()))
    # Rank within the leaf category, not across inherently expensive/cheap categories.
    products['price_percentile'] = products.groupby('category_l3').price.rank(method='average', pct=True)
    observed = events.merge(users[['user_id', 'persona']], on='user_id', validate='many_to_one')
    purchases = observed[observed.event_type == 'purchase'].merge(products, on='product_id', validate='many_to_one')
    ordered = observed.sort_values(['timestamp', 'event_id'], kind='stable').copy()
    ordered['is_view'] = ordered.event_type.eq('view').astype(int)
    ordered['views_so_far'] = ordered.groupby('user_id').is_view.cumsum()
    bought = ordered[ordered.event_type == 'purchase'].copy()
    bought['views_since_previous_purchase'] = bought.groupby('user_id').views_so_far.diff().fillna(bought.views_so_far)
    purchases = purchases.merge(bought[['event_id', 'views_since_previous_purchase']], on='event_id', validate='one_to_one')
    brand_counts = purchases.groupby(['persona', 'user_id', 'brand']).size()
    concentration = (brand_counts.groupby(['persona', 'user_id']).max() /
                     brand_counts.groupby(['persona', 'user_id']).sum()).rename('top_brand_share')
    per_persona = []
    for persona, group in users.groupby('persona', sort=True):
        activity = observed[observed.persona == persona]
        purchase = purchases[purchases.persona == persona]
        buyers = purchase.user_id.nunique()
        views = int(activity.event_type.eq('view').sum())
        denominator = int(impressions.user_id.isin(group.user_id).sum())
        shares = concentration.loc[persona] if persona in concentration.index.get_level_values(0) else pd.Series(dtype=float)
        categories = purchase.category_l1.value_counts(normalize=True).to_dict()
        per_persona.append(dict(persona=persona, users=len(group), events=len(activity),
            events_per_user=len(activity)/len(group), buyers=buyers, buyer_rate=buyers/len(group),
            purchases=len(purchase), views=views, impressions=denominator,
            purchase_per_view=len(purchase)/views if views else None,
            purchase_per_impression=len(purchase)/denominator if denominator else None,
            purchase_price_percentile_mean=float(purchase.price_percentile.mean()) if len(purchase) else None,
            top_brand_share_mean=float(shares.mean()) if len(shares) else None,
            mean_views_before_purchase=float(purchase.views_since_previous_purchase.mean()) if len(purchase) else None,
            purchase_category_shares=categories,
            configured=cfg['simulator']['personas'].get(persona, {})))
    by_persona = {row['persona']: row for row in per_persona}
    checks = dict(six_personas=len(per_persona) >= 6,
        unique_ids=all(row['duplicate_ids'] == 0 for row in integrity.values()),
        hashes=all(row['checksum_matches'] for row in integrity.values()),
        references=not any(references.values()),
        event_types={'search', 'view', 'cart', 'purchase'} <= set(events.event_type),
        category_difference=len({tuple(sorted(row['purchase_category_shares'].items())) for row in per_persona}) == len(per_persona),
        price_sensitivity=by_persona['bargain']['purchase_price_percentile_mean'] < by_persona['brand_loyal']['purchase_price_percentile_mean'],
        conversion_difference=by_persona['impulsive']['purchase_per_view'] > by_persona['careful']['purchase_per_view'],
        brand_loyalty=by_persona['brand_loyal']['top_brand_share_mean'] > max(row['top_brand_share_mean'] for row in per_persona if row['persona'] != 'brand_loyal'))
    output = output or Path(cfg['paths']['results_dir']) / 'data_audit.json'
    folder = output.parent / 'analysis'; folder.mkdir(parents=True, exist_ok=True)
    purchases.to_parquet(folder / 'purchases.parquet', index=False)
    report = dict(status='PASS' if all(checks.values()) else 'FAIL', generated_at=datetime.now(timezone.utc).isoformat(),
        data_fingerprint=manifest['generation_fingerprint'], seed=manifest['seed'], generator_version=manifest['generator_version'],
        source_hashes={str(root / name): digest for name, digest in manifest['file_hashes'].items()},
        counts=manifest['counts'], integrity=integrity, references=references, checks=checks,
        split_counts=manifest['split_counts'], boundaries=manifest['boundaries'],
        split_ratios={key: value/len(events) for key,value in manifest['split_counts'].items()},
        daily_events=events.groupby(events.timestamp.dt.strftime('%Y-%m-%d')).size().to_dict(),
        event_counts=events.event_type.value_counts().to_dict(),
        category_counts=products.category_l3.value_counts().to_dict(), brand_counts=products.brand.value_counts().to_dict(),
        price_summary=products.price.describe().to_dict(), personas=per_persona,
        purchase_ledger=str(folder / 'purchases.parquet'), purchase_ledger_sha256=file_hash(folder / 'purchases.parquet'),
        denominators=dict(activity='전체 사용자와 전체 이벤트', buyers='구매 1회 이상 사용자 / 해당 페르소나 전체 사용자',
            price='구매 이벤트별 소분류 내 전체 상품 가격 백분위 (평균 순위)',
            brand='구매자별 최다 구매 브랜드 건수 / 해당 사용자 구매 건수, 구매자 단순 평균',
            views='사용자별 직전 구매 이후 view 건수; 첫 구매는 관측 시작 이후',
            conversion='구매 이벤트 / view 또는 노출; attribution CVR과 다른 EDA 지표'),
        excluded=dict(no_purchase_users=int(len(users)-purchases.user_id.nunique()),
            null_product_events=int(events.product_id.isna().sum()), ledger_rows_dropped=int((events.event_type=='purchase').sum()-len(purchases))),
        limitations=['가성비는 품질·효용 관측값이 없는 저가격 선호 대리모형입니다.',
            '페르소나는 생성기 진단에만 사용하며 추천 모델 입력으로 사용하지 않습니다.',
            '분포 차이는 관측 기술 통계이며 실제 고객에 대한 인과 효과가 아닙니다.'])
    write_json(output, report)
    log('데이터', 'EDA', f"상품={len(products):,} / 사용자={len(users):,} / 이벤트={len(events):,} / 판정={report['status']} / 결과={output}", status='완료')
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = audit(load_config(), args.output)
    emit_json(result)
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(run_cli(main, '데이터 분석', '데이터 manifest와 관측 분모·검사 결과를 확인하세요. 기존 버전은 보존하세요.'))

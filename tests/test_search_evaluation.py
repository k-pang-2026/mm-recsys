import pandas as pd
import pytest
from src.search.bm25 import BM25Search
from src.search.eval_support import relevant_ids


def test_bm25_aliases_and_candidate_availability_match():
    model = BM25Search(['X1', 'X2', 'X3', 'X4'],
                       ['black shirt', 'red boots', 'blue scarf', 'white jeans'])
    assert model.search('검은색 셔츠', 1)[0].product_id == 'X1'
    assert model.search('검은색 셔츠', 4) == model.search('black shirt', 4)
    assert [h.product_id for h in model.search('black shirt', 10, {'X2'})] == ['X2']


def test_image_relevance_cannot_depend_on_unobservable_brand():
    products = pd.DataFrame({'product_id': ['A', 'B', 'C'], 'category_l1': ['tops']*3,
        'color': ['black']*3, 'brand': ['North', 'Urban', 'North'],
        'created_at': pd.to_datetime(['2025-01-01', '2025-01-01', '2026-01-01'], utc=True)})
    cutoff = pd.Timestamp('2025-12-01', tz='UTC')
    assert relevant_ids(products, {'category_l1': 'tops', 'color': 'black'}, 'image', cutoff) == {'A', 'B'}
    with pytest.raises(ValueError, match='observable'):
        relevant_ids(products, {'brand': 'North'}, 'image')
    assert relevant_ids(products, {'brand': 'North'}, 'text', cutoff) == {'A'}

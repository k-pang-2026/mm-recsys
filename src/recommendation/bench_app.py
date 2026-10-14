"""B-owned TCP benchmark factory; shared server/routes/schema remain unchanged."""
import json
import os
from src.common.config import load_config
from src.recommendation.feature_store import RecommendationFeatureStore
from src.recommendation.datasets import read_data
from src.serving.main import create_app


def create_bench_app():
    cfg=load_config()
    cfg['recommend']['scoring']=json.loads(os.environ['B_BENCH_SCORING'])
    b5=os.environ.get('B_BENCH_B5','1')=='1'
    cfg['recommend']['enable_reranking']=b5;cfg['recommend']['session']['enabled']=b5
    cfg['serving']['plugins']['search']='src.recommendation.no_search_plugin'
    data=read_data(cfg['paths']['data_dir'])
    return create_app(cfg,feature_store=RecommendationFeatureStore(cfg,data['products']))

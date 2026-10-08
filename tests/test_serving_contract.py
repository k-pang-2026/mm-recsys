from fastapi.testclient import TestClient
from src.common.schemas import EventRequest,FeedbackRequest,SearchResponse,SearchItem
from src.serving.main import create_app
from src.serving.memory_store import MemoryFeatureStore


def test_unimplemented_models_never_report_empty_success():
    with TestClient(create_app()) as client:
        assert client.get('/health').status_code==200
        assert client.get('/ready').status_code==503
        assert client.post('/api/search',json={}).status_code==422
        assert client.post('/api/search',json={'query_text':'black shirt'}).status_code==503
        assert client.get('/api/recommend',params={'user_id':'new'}).status_code==503
        body={'event_id':'e1','user_id':'u','product_id':'p','event_type':'view','category':'tops'}
        assert client.post('/api/event',json=body).json()['features']['recent_clicks']==['p']
        assert client.post('/api/event',json=body).json()['applied'] is False


def test_store_session_reset_expiry_and_feedback_idempotence():
    now=[0.0];store=MemoryFeatureStore(2,10,20,clock=lambda:now[0])
    for i in range(3):store.append_event(EventRequest(event_id=str(i),user_id='u',product_id=str(i),event_type='view'))
    assert store.get_features('u').recent_clicks==['1','2']
    assert store.get_features('u').session_clicks==3
    feedback=FeedbackRequest(event_id='x',user_id='u',product_id='p',event_type='purchase')
    assert store.update_reward(feedback) and not store.update_reward(feedback)
    assert store.rewards['p']['purchases']==1
    now[0]=11;assert store.get_features('u').session_clicks==0
    store.batch_load_profiles({'u':{'age_group':'25-34'}})
    features=store.get_features('u');features.profile['age_group']='changed'
    assert store.get_features('u').profile['age_group']=='25-34'


def test_search_plugin_receives_shared_model_and_preserves_api_schema():
    class Fake:
        def search(self,request):
            return SearchResponse(search_type='text',results=[SearchItem(product_id='p',name=request.query_text,score=.5,price=100)],latency_ms=1,total_count=1)
    with TestClient(create_app(search_service=Fake())) as client:
        body=client.post('/api/search',json={'query_text':'shirt'}).json()
        assert set(body)=={'search_type','results','latency_ms','total_count'}
        assert body['results'][0]['product_id']=='p'


def test_invalid_image_fails_validation_before_model_loading():
    with TestClient(create_app()) as client:
        assert client.post('/api/search',json={'query_image':'not-base64'}).status_code==422

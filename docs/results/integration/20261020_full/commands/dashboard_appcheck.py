import hashlib,json,sys,time
from pathlib import Path
from streamlit.testing.v1 import AppTest
expected=sys.argv[1];started=time.perf_counter()
app=AppTest.from_file('/app/dashboard/app.py',default_timeout=90).run()
assert not app.exception,[x.value for x in app.exception]
assert [tab.label for tab in app.tabs]==['검색','추천','A/B 실험','시스템']
assert app.selectbox[0].value.name=='evaluation_full_test.json'
metrics={m.label:m.value for m in app.metric}
assert metrics['측정 기준 판정']=='PASS' and metrics['최종 종합 품질']==expected
assert metrics['API 연결']=='정상' and metrics['모델 준비']=='준비됨'
app.text_input(key='query_text').set_value('black shirt')
next(b for b in app.button if b.label=='검색 실행').click().run()
assert not app.exception and not app.error
search=[x.value for x in app.dataframe if 'product_id' in x.value.columns]
assert len(search)==1 and len(search[0])==10
app.text_input(key='user_id').set_value('U000001')
next(b for b in app.button if b.label=='추천 실행').click().run()
assert not app.exception and not app.error
recommend=[x.value for x in app.dataframe if 'product_id' in x.value.columns]
assert len(recommend)==1 and len(recommend[0])==10
value=json.loads(Path('/app/docs/results/docker/runtime/full/evaluation_full_test.json').read_text())
if expected=='PASS':
    assert value['ab']['status']=='MEASURED' and value['ab']['days']==30
    for arm,label in [('control','Control CVR'),('treatment','Treatment CVR')]:
        assert value['ab']['arms'][arm]['users']==5000
        assert metrics[label]==f"{value['ab']['arms'][arm]['cvr']:.4%}"
    ct=value['integration']['ct']
    assert any(ct['retraining'] in item.value and '교체·복구 검사 PASS' in item.value for item in app.info)
    assert all(c['status']=='PASS' and c['exit_code']==0 for c in value['integration']['checks'].values())
report=dict(status='PASS',scale='full',data_fingerprint=value['data_fingerprint'],acceptance_displayed=expected,quality_displayed=metrics['측정 기준 판정'],selected_report=app.selectbox[0].value.name,search_results=10,recommendation_results=10,metrics=metrics,tabs=[x.label for x in app.tabs],exceptions=0,source_hashes={str(p.relative_to('/app')):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path('/app/dashboard/app.py'),Path('/app/dashboard/data.py')]},seconds=time.perf_counter()-started,scope='actual standalone dashboard container Streamlit AppTest and real API forms; no mocks; no browser pixel assertion')
print('RESULT_JSON='+json.dumps(report,ensure_ascii=False))

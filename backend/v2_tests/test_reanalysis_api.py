import copy
import subprocess
from pathlib import Path
from v2_fixture import v2app,user_client
from test_analysis_api import essay,analyze
from test_library_api import upload


def test_four_reactions_persist_without_altering_analysis(v2app):
    c,h,_=user_client(v2app);w=essay(c,h,'나는 할수 있다.');ids=analyze(v2app,c,h,w).json['data'];run=c.get('/api/analyses/'+ids['analysisId']).json['data']
    raw=copy.deepcopy(run['result']);finding=next(f for f in run['findings'] if f['type']=='spelling')
    for action,status in [('confirm','confirmed'),('fixed','fixed'),('ignore','ignored'),('incorrect','incorrect')]:
        response=c.post('/api/findings/'+finding['id']+'/actions',headers=h,json={'action':action});assert response.status_code==200 and response.json['data']['status']==status
    assert c.get('/api/analyses/'+ids['analysisId']).json['data']['result']==raw
    assert c.post('/api/findings/'+finding['id']+'/apply',headers=h).status_code==409


def test_reaction_idor_and_reanalysis_version_comparison(v2app):
    c,h,_=user_client(v2app);w=essay(c,h,'나는 할수 있다.');first=analyze(v2app,c,h,w).json['data']
    finding=c.get('/api/analyses/'+first['analysisId']).json['data']['findings'][0]
    other,oh,_=user_client(v2app,'synthetic-other')
    assert other.post('/api/findings/'+finding['id']+'/actions',headers=oh,json={'action':'confirm'}).status_code==404
    second=analyze(v2app,c,h,w,body='나는 할 수 있다.').json['data']
    comparison=c.get('/api/analyses/'+first['analysisId']+'/compare/'+second['analysisId']).json['data']
    assert comparison['left']['versionId']!=comparison['right']['versionId']
    assert c.get('/api/analyses/'+first['analysisId']).json['data']['sourceVersion']['content']=='나는 할수 있다.'


def test_existing_frontend_unicode_repeat_and_edit_golden():
    root=Path(__file__).parents[2]
    completed=subprocess.run(['node','scripts/book-layout.test.mjs'],cwd=root,capture_output=True,text=True,timeout=30)
    assert completed.returncode==0,completed.stderr


def test_selected_edition_similarity_configuration_frozen_per_run(v2app):
    c,h,_=user_client(v2app);d=upload(c,h,'그는 조용히 문을 열었다.').json['data'];w=essay(c,h,'“그는 조용히 문을 닫었다.”')
    c.post('/api/writings/'+w['id']+'/documents',headers=h,json={'revisionId':d['latestRevisionId']})
    c.patch('/api/settings',headers=h,json={'quoteSimilarityThreshold':.8})
    first=analyze(v2app,c,h,w).json['data']
    c.patch('/api/settings',headers=h,json={'quoteSimilarityThreshold':1.0})
    second=analyze(v2app,c,h,w).json['data']
    a=c.get('/api/analyses/'+first['analysisId']).json['data'];b=c.get('/api/analyses/'+second['analysisId']).json['data']
    assert a['contextSnapshot']['quoteSimilarityThreshold']==.8 and b['contextSnapshot']['quoteSimilarityThreshold']==1.0
    assert a['result']['quoteChecks'][0]['status']=='SIMILAR_DIFFERENCE_CANDIDATE'
    assert b['result']['quoteChecks'][0]['status']=='NOT_FOUND_IN_SELECTED_REVISION'

import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]))
from sqlalchemy import event
from v2_fixture import v2app,user_client
from app.extensions import db
from app.models import Analysis
from test_analysis_api import essay


def test_essay_list_batches_analysis_summaries_without_snapshot_bodies(v2app):
    c,h,_=user_client(v2app)
    records=[essay(c,h,'가상 목록 본문 '+str(i)) for i in range(12)]
    with v2app.app_context():
        for record in records:
            db.session.add(Analysis(writing_id=record['id'],status='completed',metrics={'count':1},result_snapshot={'synthetic':'x'*10000}))
        db.session.commit()
        engine=db.engine;queries=[]
        def capture(_conn,_cursor,statement,*_args):
            if statement.lstrip().upper().startswith('SELECT') and 'FROM analysis' in statement:queries.append(statement)
        event.listen(engine,'before_cursor_execute',capture)
    try:
        response=c.get('/api/writings?pageSize=12')
        assert response.status_code==200
        data=response.json['data'];assert len(data)==12
        assert len(queries)==1
        assert all('result_snapshot' not in q and 'input_manifest' not in q and 'context_snapshot' not in q for q in queries)
        assert all(len(item['analysisRuns'])==1 and item['latestAnalysisId']==item['analysisRuns'][0]['id'] for item in data)
        assert all('content' not in item for item in data)
        optimized_queries=len(queries);queries.clear()
        with v2app.app_context():
            for record in records:Analysis.query.filter_by(writing_id=record['id']).all()
        assert len(queries)==12 and all('result_snapshot' in q for q in queries)
        import json
        evidence=Path('artifacts/code-review');evidence.mkdir(parents=True,exist_ok=True)
        (evidence/'list-query-benchmark.json').write_text(json.dumps({'essays':12,'analysisQueriesBefore':len(queries),'analysisQueriesAfter':optimized_queries,'snapshotSelectedBefore':True,'snapshotSelectedAfter':False,'wireContractPreserved':True}),encoding='utf-8')
    finally:event.remove(engine,'before_cursor_execute',capture)


def test_selected_document_permission_does_not_search(monkeypatch,v2app):
    from app.v2 import quote_api
    from test_library_api import upload
    from app.v2.common import principal
    from app.models import User
    c,h,uid=user_client(v2app)
    document=upload(c,h,'가상 작품 본문').json['data']
    with v2app.app_context():
        from app.models import DocumentRevision
        revision=db.session.get(DocumentRevision,document['latestRevisionId'])
        context={'documents':[{'revisionId':revision.id,'documentId':document['id'],'sha256':revision.content_hash}],'quoteSimilarityThreshold':0.8}
        monkeypatch.setattr(quote_api,'match_quote',lambda *a,**k:(_ for _ in ()).throw(AssertionError('Permission verification must not search')))
        result,threshold=quote_api.selected_for_context(context,principal(db.session.get(User,uid)))
        assert len(result)==1 and threshold==80

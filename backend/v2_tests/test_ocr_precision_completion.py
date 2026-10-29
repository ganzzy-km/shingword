"""Development contracts fixed before execution; no independent accuracy labels."""
import copy,sys
from pathlib import Path
import pytest
from PIL import Image,ImageDraw
from v2_fixture import v2app
from test_ocr_api import setup,ready
sys.path.insert(0,str(Path(__file__).parents[1]))
from app.services import ocr_pipeline as p


def trusted(angle):
    return {'applied':True,'angle':angle,'verification':{'allowed':True,'basis':'IMAGE_ROWS_AND_SAME_RECOGNIZER_VIEW_COMPARISON'}}


@pytest.mark.parametrize('angle',[90,180,270])
def test_selected_region_reuses_verified_parent_orientation_and_inverse(angle):
    source=Image.new('RGB',(180,120),'white');ImageDraw.Draw(source).rectangle([30,30,55,45],fill='black');before=source.tobytes()
    crop=source.crop((20,10,120,90));expected,_=p.orthogonal_view(crop,angle)
    view,meta=p.prepare_region_view(source,[20,10,120,90],mode='precise',parent_orientation=trusted(angle))
    assert view.size==expected.size and view.tobytes()==expected.tobytes() and source.tobytes()==before
    a=meta['inverseAffineToOriginalPage'];corners=[(a[0]*x+a[1]*y+a[2],a[3]*x+a[4]*y+a[5]) for x,y in [(0,0),(view.width,0),(0,view.height),(view.width,view.height)]]
    assert [min(x for x,y in corners),min(y for x,y in corners),max(x for x,y in corners),max(y for x,y in corners)]==[20,10,120,90]
    assert meta['angle']==angle and meta['parentOrientationUsed'] and meta['sourcePreserved']


@pytest.mark.parametrize('bad',[{'applied':True,'angle':45}, {'applied':True,'angle':90}, {'applied':True,'angle':90,'verification':{'allowed':False}},trusted(True)])
def test_uncorroborated_or_invalid_parent_orientation_fails_closed(bad):
    with pytest.raises(ValueError):p.prepare_region_view(Image.new('RGB',(100,100)),[0,0,50,50],mode='precise',parent_orientation=bad)


def test_ordinary_region_is_identical_and_never_uses_orientation():
    im=Image.new('RGB',(100,80),'red')
    view,meta=p.prepare_region_view(im,[10,20,60,70],mode='standard',parent_orientation=None)
    assert view.tobytes()==im.crop((10,20,60,70)).tobytes() and meta['angle']==0
    with pytest.raises(ValueError):p.prepare_region_view(im,[10,20,60,70],mode='standard',parent_orientation=trusted(90))


def line(identifier,text,box,block=0,kind='text'):
    return {'id':identifier,'text':text,'box':box,'block':block,'blockType':kind,'engine':'fixture','includedInDraft':True}


def prose(a=None,b=None,profile='prose'):
    a=a or line('one','긴 첫 줄😀은 다음 줄로',[10,10,250,30]);b=b or line('two','계속 이어지는 인쇄 문장이다.',[10,40,245,60]);im=Image.new('RGB',(300,160),'white')
    draft=p.compose_draft([a,b],profile=profile)
    return draft,p.literary_structure(im,[a,b],draft,profile)


def test_prose_print_wrap_is_an_exact_manual_review_span_not_an_auto_edit():
    draft,layout=prose();wraps=layout['lineWrapCandidates'];assert len(wraps)==1
    w=wraps[0];assert draft['text'][w['start']:w['end']]=='\n'
    assert w['fromLineId']=='one' and w['toLineId']=='two' and w['status']=='USER_REVIEW_ONLY'
    assert layout['textUnchanged'] and not w['automaticallyApplied']


@pytest.mark.parametrize('change',['poetry','drama','different_block','table','unknown_block','indent','blank','terminal','native','reverse'])
def test_wrap_review_does_not_join_paragraphs_tables_or_unrelated_lines(change):
    a=line('one','문장의 앞부분',[10,10,250,30]);b=line('two','문장의 이어지는 부분',[10,40,245,60]);profile='prose'
    if change in {'poetry','drama'}:profile=change
    elif change=='different_block':b['block']=1
    elif change=='table':a['blockType']=b['blockType']='table'
    elif change=='unknown_block':a['block']=b['block']=None
    elif change=='indent':b['box']=[55,40,245,60]
    elif change=='blank':b['box']=[10,95,245,115]
    elif change=='terminal':a['text']+='.'
    elif change=='native':a['engine']='native'
    elif change=='reverse':b['box']=[10,0,245,20]
    draft,layout=prose(a,b,profile);assert not layout.get('lineWrapCandidates')


def test_ruled_cells_obey_existing_column_span_contract():
    im=Image.new('RGB',(300,200),'white');draw=ImageDraw.Draw(im)
    for x in [10,110,210]:draw.line([x,10,x,150],fill='black',width=2)
    for y in [10,80,150]:draw.line([10,y,210,y],fill='black',width=2)
    result=p.bind_ruled_cells(im,{'blocks':[{'type':'table','box':[10,10,210,150]}],'tables':[]},[line('1','문자',[20,25,90,50])])
    assert len(result['tables'][0]['cells'])==4
    assert all(c['columnSpan']==1 and c['rowSpan']==1 and 'colSpan' not in c for c in result['tables'][0]['cells'])


@pytest.mark.parametrize('angle',[90,180,270])
def test_actual_worker_region_boundary_uses_parent_and_maps_result(tmp_path,angle):
    sys.path.insert(0,str(Path(__file__).parents[1]/'app/services'))
    from ocr_models import run
    source=tmp_path/'source.png';Image.new('RGB',(180,120),'white').save(source)
    expected,_=p.orthogonal_view(Image.new('RGB',(100,80),'white'),angle)
    class Models:
        def region(self,image,engine,mode):
            assert image.size==expected.size and engine=='paddle' and mode=='precise'
            return {'text':'실행 경계 시험','lines':[{'text':'실행 경계 시험','box':[0,0,image.width,image.height]}],'engine':engine}
        def versions(self,_):return {'fixture':'Not actual inference'}
    r=run({'config':{'models':str(tmp_path/'models')},'operation':'region','input':str(source),'box':[20,10,120,90],'ocrMode':'precise','engine':'paddle','parentOrientation':trusted(angle)},Models())
    assert r['lines'][0]['box']==[20,10,120,90] and r['preprocessing']['angle']==angle and r['coordinateFrame']=='ORIGINAL_PAGE_PIXELS'


def test_coordinator_orientation_comes_only_from_owned_parent(tmp_path,monkeypatch):
    from app.services import ocr_jobs as jobs
    monkeypatch.setattr(jobs,'local_file',lambda name:tmp_path/name)
    page={'imageFile':'own-page.png','preprocessing':trusted(90)}
    r=jobs.region_worker_input(page,[1,2,30,40],'tesseract-line','precise')
    assert r['parentOrientation']==page['preprocessing'] and r['input']==str(tmp_path/'own-page.png')
    r['parentOrientation']['angle']=180;assert page['preprocessing']['angle']==90
    assert jobs.region_worker_input(page,[1,2,30,40],'paddle','standard')['parentOrientation'] is None


def test_joined_review_saved_confirmed_and_prior_revision_remains_immutable(setup):
    from app.models import DocumentRevision
    from app.extensions import db
    app,c,headers,owner,did,jid,doc,_=setup
    original='앞 문장😀\n다음 문장';joined='앞 문장😀 다음 문장'
    ready(app,jid,original)
    first=c.post('/api/ocr-jobs/'+jid+'/confirm',headers=headers,json={'expectedDraftVersion':1,'expectedRevisionId':doc['latestRevisionId']})
    assert first.status_code==201;first_id=first.json['data']['revisionId']
    created=c.post('/api/source-documents/'+did+'/ocr',headers=headers,json={'expectedRevisionId':first_id,'ocrMode':'precise','ocrProfile':'prose'})
    assert created.status_code==202;next_id=created.json['data']['id'];assert next_id!=jid
    ready(app,next_id,original)
    saved=c.patch('/api/ocr-jobs/'+next_id+'/draft',headers=headers,json={'expectedDraftVersion':1,'pages':{'1':joined}})
    assert saved.status_code==200 and saved.json['data']['pages'][0]['draft']==joined
    second=c.post('/api/ocr-jobs/'+next_id+'/confirm',headers=headers,json={'expectedDraftVersion':2,'expectedRevisionId':first_id})
    assert second.status_code==201;second_id=second.json['data']['revisionId'];assert second_id!=first_id
    with app.app_context():
        assert db.session.get(DocumentRevision,first_id).content==original
        assert db.session.get(DocumentRevision,second_id).content==joined
    detail=c.get('/api/source-documents/'+did).json['data']
    assert detail['latestRevisionId']==second_id and detail['content']==joined

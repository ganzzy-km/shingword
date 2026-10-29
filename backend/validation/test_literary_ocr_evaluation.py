import hashlib,json,sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parent))
from evaluate_literary_ocr import cer,page_metrics,validate_manifest,cluster_interval,evaluate

def test_strict_cer_does_not_hide_spaces_quotes_newlines_or_emoji():
    assert cer('가 😀\n“나”','가😀나')['errors']==4
    assert cer('','')['CER'] is None

def bundle(tmp_path,classification='SYNTHETIC_PRINTED'):
    items=[]
    for i,split in enumerate(['development','evaluation']):
        ref={'text':'첫 행\n둘째 행😀'};input_data=('synthetic-input-'+str(i)).encode();(tmp_path/f'in{i}').write_bytes(input_data)
        files={'input':f'in{i}','reference':f'ref{i}.json','standardResult':f'std{i}.json','preciseResult':f'pre{i}.json'}
        (tmp_path/files['reference']).write_text(json.dumps(ref),encoding='utf-8')
        inputsha=hashlib.sha256(input_data).hexdigest()
        for mode,key in [('standard','standardResult'),('precise','preciseResult')]:
            (tmp_path/files[key]).write_text(json.dumps({'ocrMode':mode,'inputSha':inputsha,'draft':{'text':ref['text']},'localRefinement':{'automaticallyChangedCharacters':0}}),encoding='utf-8')
        items.append({'id':str(i),'workId':'original-'+str(i),'revisionId':'v1','scanGroup':'scan-'+str(i),'split':split,'genre':'poetry','classification':classification,'inputSha':inputsha,**files,**{k+'Sha':hashlib.sha256((tmp_path/v).read_bytes()).hexdigest() for k,v in files.items()}})
    return {'pages':items}

def test_synthetic_data_cannot_certify_actual_advantage(tmp_path):
    result=evaluate(bundle(tmp_path),tmp_path)
    assert result['pages']==2 and result['PRECISION_ADVANTAGE']=='UNVERIFIED_DATA' and result['actualUnusedRealPages']==0

@pytest.mark.parametrize('defect',['group','hash','rights','path'])
def test_bad_split_hash_rights_and_path_rejected(tmp_path,defect):
    m=bundle(tmp_path)
    if defect=='group':m['pages'][1].update(workId='original-0',revisionId='v1',scanGroup='scan-0')
    if defect=='hash':m['pages'][0]['referenceSha']='bad'
    if defect=='rights':m['pages'][0]['classification']='REAL_LITERARY'
    if defect=='path':m['pages'][0]['reference']='../not-allowed'
    with pytest.raises(ValueError):validate_manifest(m,tmp_path)

def test_missing_human_correction_or_structural_labels_stays_unmeasured():
    r=page_metrics({'text':'한 줄'}, {'draft':{'text':'한줄'}})
    assert r['structure'] is None and r['humanReviewSeconds'] is None and r['strict']['errors']==1
    assert cluster_interval([])['interval'] is None


def test_whitespace_diagnostic_still_counts_punctuation_and_insertions():
    r=page_metrics({'text':'가 나.\n다'}, {'draft':{'text':'가나?다X'},'seconds':1.5})
    assert r['whitespaceExcludedDiagnostic']['errors']==2
    assert sum(r['editOperations'].values())==r['strict']['errors'] and r['seconds']==1.5
    assert page_metrics({'text':'가'},{'draft':{'text':'가X'}})['editOperations']['insert']==1
    assert r['actualHumanReviewSeconds'] is None


def test_selector_new_errors_and_manual_work_are_not_hidden_by_net_gain():
    p={'draft':{'text':'바른 문장?'},'precision':{'before':{'text':'바를문장.'},'decisions':[{'status':'APPLIED'}]}}
    r=page_metrics({'text':'바른 문장.'},p)
    assert r['automaticSelection']['newErrorUnits']==1
    assert r['automaticSelection']['removedErrorUnits']>=1
    assert r['minimumManualCodePointEdits']==1


def test_line_coordinates_and_duplicate_counts_are_separate():
    ref={'text':'첫 행\n다음 행','lines':[{'id':'r1','text':'첫 행','box':[0,0,100,20]}, {'id':'r2','text':'다음 행','box':[0,40,100,60]}]}
    p={'draft':{'text':'첫 행\n첫 행'},'lines':[{'id':'one','text':'첫 행','box':[0,0,100,20],'includedInDraft':True}]}
    r=page_metrics(ref,p)
    assert r['missingExactLines']==1 and r['extraOrDuplicateExactLines']==1 and r['geometricMissingLines']==1


def test_same_work_different_editions_cannot_cross_final_split(tmp_path):
    m=bundle(tmp_path);m['pages'][1].update(workId=m['pages'][0]['workId'],revisionId='different-edition')
    with pytest.raises(ValueError,match='GROUP_LEAKAGE'):validate_manifest(m,tmp_path)


def test_regression_split_is_distinct_and_never_independent(tmp_path):
    m=bundle(tmp_path);m['pages'][0]['split']='regression'
    assert validate_manifest(m,tmp_path)==2
    assert evaluate(m,tmp_path)['independentAccuracyCertification'] is False

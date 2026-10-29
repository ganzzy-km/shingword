import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from evaluate_literary_ocr import page_metrics


def test_table_metrics_are_separate_and_never_erase_page_space_errors():
    ref={'text':'가        나','tableCells':[{'row':0,'column':0,'text':'가'},{'row':0,'column':1,'text':'나'}]}
    page={'draft':{'text':'가\n나'},'structure':{'tables':[{'cells':[{'row':0,'column':0,'rowSpan':1,'columnSpan':1,'text':'가'},{'row':0,'column':1,'text':'나'}]}]}}
    m=page_metrics(ref,page);assert m['strict']['errors']>0 and m['structuredTable']['cellTextCER']['errors']==0
    assert m['structuredTable']['TP']==2 and m['structuredTable']['FP']==m['structuredTable']['FN']==0


def test_unlabelled_table_or_order_is_not_certified():
    m=page_metrics({'text':'원문'}, {'draft':{'text':'원문'},'structure':{'tables':[{'cells':[]}]}})
    assert m['structuredTable'] is None and m['labelledReadingOrder'] is None


def test_wrong_span_and_duplicate_cells_are_real_false_results():
    m=page_metrics({'text':'가','tableCells':[{'row':0,'column':0,'columnSpan':2,'text':'가'}]},
        {'draft':{'text':'가'},'structure':{'tables':[{'cells':[{'row':0,'column':0,'columnSpan':1,'text':'가'}]*2}]}})
    assert m['structuredTable']['TP']==0 and m['structuredTable']['FP']==2 and m['structuredTable']['FN']==1


def test_missing_line_is_not_perfect_reading_order():
    m=page_metrics({'text':'가','lines':[{'id':'r','text':'가','box':[0,0,100,20]}]}, {'draft':{'text':'가'},'lines':[]})
    assert m['labelledReadingOrder']['measurable'] is False


def test_reverse_emitted_order_is_detected():
    ref={'text':'가\n나','lines':[{'id':'r1','text':'가','box':[0,0,100,20]},{'id':'r2','text':'나','box':[0,40,100,60]}]}
    m=page_metrics(ref,{'draft':{'text':'나\n가','lineMap':[{'lineId':'b'},{'lineId':'a'}]},'lines':[{'id':'a','text':'가','box':[0,0,100,20]},{'id':'b','text':'나','box':[0,40,100,60]}]})
    assert m['labelledReadingOrder']['measurable'] and not m['labelledReadingOrder']['exact']

"""Geometry-only regressions fixed before implementation; not OCR truth labels."""
import copy,random
import pytest
from app.services.ocr_pipeline import precision_reading_order

def columns(gap,scale=1,footer=False,heading=False):
    def line(i,box,block):return {'id':i,'text':i,'box':[v*scale for v in box],'block':block,'includedInDraft':True}
    rows=[line('header',[20,0,580 if heading else 200,20],0),line('author',[20,40,180,60],1)]
    for i in range(5):
        y=200+i*(20+gap)
        rows.extend([line('left-'+str(i),[20,y,200,y+20],i+2),line('right-'+str(i),[360,y,560,y+20],i+2)])
    expected=['header','author']+['left-'+str(i) for i in range(5)]+['right-'+str(i) for i in range(5)]
    if footer:
        y=200+4*(20+gap)+20+max(160,gap*3)
        rows.append(line('footer',[20,y,220,y+20],99));expected.append('footer')
    random.Random(104).shuffle(rows)
    return rows,expected

@pytest.mark.parametrize('gap',[50,80,120])
@pytest.mark.parametrize('scale',[1,2])
def test_repeated_column_row_gaps_are_not_page_boundaries(gap,scale):
    rows,expected=columns(gap,scale);before=copy.deepcopy(rows)
    ordered=precision_reading_order(rows,{},600*scale)
    assert [l['id'] for l in ordered]==expected
    assert rows==before
    assert len({l['id'] for l in ordered})==len(rows)

@pytest.mark.parametrize('gap',[50,80,120])
@pytest.mark.parametrize('heading',[False,True])
def test_actual_outer_footer_gap_still_follows_both_columns(gap,heading):
    rows,expected=columns(gap,footer=True,heading=heading)
    assert [l['id'] for l in precision_reading_order(rows,{},600)]==expected

def test_confirmed_table_rows_do_not_become_text_columns():
    rows,_=columns(80)
    order=precision_reading_order(rows,{'blocks':[{'type':'table','box':[0,190,600,700]}]},600)
    assert [l['id'] for l in order]==['header','author']+[x for i in range(5) for x in ['left-'+str(i),'right-'+str(i)]]

def test_one_column_and_ambiguous_full_width_middle_keep_literal_metadata():
    rows=[{'id':str(i),'text':'동일한 문구','box':[20,100*i,550,100*i+20],'block':i} for i in range(8)]
    shuffled=list(reversed(rows));before=copy.deepcopy(shuffled)
    result=precision_reading_order(shuffled,{},600)
    assert [l['id'] for l in result]==[str(i) for i in range(8)]
    assert shuffled==before and result==rows

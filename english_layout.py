"""Coordinate-based extraction for English six-column service invoices.
Uncertain names/dates remain empty; this is a bounded layout parser, not a general model.
"""
import re
from datetime import datetime
from invoice_parsing import normalize, number


def cells(data):
    data = data.get('res', data)
    texts, boxes = data['rec_texts'], data['rec_boxes']
    if len(texts) != len(boxes): raise ValueError('OCR text/box counts differ')
    return [(str(t).strip(), *map(float,b)) for t,b in zip(texts,boxes)]


def right_value(rows, pattern):
    anchors = [r for r in rows if re.fullmatch(pattern,normalize(r[0]))]
    if len(anchors) != 1: return None
    _,x,y,x2,y2 = anchors[0]
    cy=(y+y2)/2
    candidates=[r for r in rows if r[1]>=x2 and abs((r[2]+r[4])/2-cy) <= (y2-y)*0.55]
    candidates.sort(key=lambda r:r[1])
    return candidates[0][0] if candidates else None


def fields(data):
    rows=cells(data)
    if not any(normalize(r[0]) == 'INVOICE ID' for r in rows): return None
    warnings=[]
    raw_date=right_value(rows,r'INVOICE DATE')
    due=right_value(rows,r'DUE DATE')
    valid=[]
    for fmt in ['%m/%d/%Y','%d/%m/%Y']:
        try:
            d=datetime.strptime(raw_date or '',fmt).date()
            if due: datetime.strptime(due,fmt)
            valid.append(d.isoformat())
        except ValueError: pass
    date=valid[0] if valid and len(set(valid))==1 else None
    if date: warnings.append('Date order inferred from invoice and due date; confirm against the document.')
    else: warnings.append('Date format is ambiguous or invalid; enter the confirmed ISO date manually.')
    currencies={m.group(1).upper() for r in rows for m in re.finditer(r'\b(?:Total|Unit price)\s*\(([A-Z]{3})\)',r[0],re.I)}
    def amount(pattern,discount=False):
        candidates = rows
        if pattern.startswith('TOTAL'):
            boundaries = [r[2] for r in rows if normalize(r[0]) in {'SUB TOTAL', 'SUBTOTAL'}]
            if len(boundaries) != 1: return None
            candidates = [r for r in rows if r[2] >= boundaries[0]]
        raw=right_value(candidates,pattern)
        if raw is None: return None
        try:
            n=number(raw.lstrip('-').strip() if discount else raw)
            return format(n,'.2f')
        except ValueError: return None
    discount_present=any(normalize(r[0]).startswith('DISCOUNT') for r in rows)
    return dict(invoice_number=right_value(rows,r'INVOICE ID'),invoice_date=date,
                currency=next(iter(currencies)) if len(currencies)==1 else None,
                subtotal=amount(r'SUB\s*TOTAL'),tax_amount=amount(r'TAX(?:\s*\([\d.,]+%\))?'),
                total=amount(r'TOTAL\s*\([A-Z]{3}\)'),
                discount_amount=amount(r'DISCOUNT(?:\s*\([\d.,]+%\))?',True) if discount_present else '0.00',
                extraction_warnings=warnings)


def items(data):
    rows=cells(data)
    labels={'#':'index','DESCRIPTION':'description','QTY':'quantity','UNITS':'unit'}
    heads={}
    for r in rows:
        name=normalize(r[0])
        key=labels.get(name)
        if re.fullmatch(r'UNIT PRICE\s*\([A-Z]{3}\)',name): key='unit_price'
        # Exclude the summary Total by requiring the same y as Description later.
        if re.fullmatch(r'TOTAL\s*\([A-Z]{3}\)',name): key='line_total'
        if key: heads.setdefault(key,[]).append(r)
    try:
        desc=heads.get('description',[])
        if len(desc)!=1: raise ValueError('English table description heading missing or repeated.')
        baseline=(desc[0][2]+desc[0][4])/2
        header={}
        for key in ['index','description','quantity','unit','unit_price','line_total']:
            candidates=[r for r in heads.get(key,[]) if abs((r[2]+r[4])/2-baseline)<20]
            if len(candidates)!=1: raise ValueError('Six English table columns could not be located uniquely.')
            header[key]=candidates[0]
        ordered=sorted(header,key=lambda k:header[k][1])
        if ordered != ['index','description','quantity','unit','unit_price','line_total']:
            raise ValueError('Unsupported English column order.')
        stops=[r[2] for r in rows if normalize(r[0]) in {'SUB TOTAL','SUBTOTAL'} and r[2]>baseline]
        if len(stops)!=1: raise ValueError('Subtotal boundary missing or repeated.')
        bottom=stops[0]
        centers=[(header[k][1]+header[k][3])/2 for k in ordered]
        bounds=[(header[a][3]+header[b][1])/2 for a,b in zip(ordered,ordered[1:])]
        def column(r):
            x=(r[1]+r[3])/2
            return ordered[sum(x>b for b in bounds)]
        body=[r for r in rows if r[2]>max(h[4] for h in header.values()) and r[4]<bottom]
        anchors=sorted([r for r in body if column(r)=='index' and re.fullmatch(r'\d+',r[0])],key=lambda r:r[2])
        if not anchors or [int(r[0]) for r in anchors]!=list(range(1,len(anchors)+1)):
            raise ValueError('Item row numbers missing or discontinuous.')
        result=[]
        for i,anchor in enumerate(anchors):
            cy=(anchor[2]+anchor[4])/2
            end=(anchors[i+1][2]+anchors[i+1][4])/2-8 if i+1<len(anchors) else bottom
            group=[r for r in body if cy-12 <= (r[2]+r[4])/2 < end]
            description=sorted([r for r in group if column(r)=='description'],key=lambda r:(r[2],r[1]))
            if not description: raise ValueError('Item description missing.')
            row={'description':'\n'.join(r[0] for r in description)}
            for key in ['quantity','unit_price','line_total']:
                values=[r[0] for r in group if column(r)==key]
                if len(values)!=1: raise ValueError('Missing or ambiguous numeric item cell.')
                raw=re.sub(r'^[x×]\s*','',values[0]) if key=='quantity' else values[0]
                n=number(raw)
                if key=='quantity' and n<=0: raise ValueError('Quantity must be positive.')
                row[key]=str(n) if key=='quantity' else format(n,'.2f')
            result.append(row)
        return dict(items=result,extraction_status='EXTRACTED',warnings=[])
    except ValueError as error:
        return dict(items=[],extraction_status='NEEDS_REVIEW',warnings=[str(error)])


def parties(data):
    rows=cells(data)
    anchors=[r for r in rows if normalize(r[0])=='INVOICE ID']
    if len(anchors)!=1: return None
    top=anchors[0][2]
    # Repeated brand in logo and company block provides stronger evidence than a lone title.
    names={r[0] for r in rows if r[4]<top and sum(s[0]==r[0] for s in rows if s[4]<top)>1}
    supplier=next(iter(names)) if len(names)==1 else None
    customer=[r[0] for r in rows if r[1]>anchors[0][3]+100 and top<=r[2]<top+50
              and re.search(r'\b(?:Ltd\.?|LLC|Inc\.?|SARL)\s*$',r[0],re.I)]
    return dict(supplier_name=supplier,customer_name=customer[0] if len(customer)==1 else None)

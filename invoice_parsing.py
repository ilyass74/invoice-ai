"""Conservative extraction for supported French invoice layouts; no OCR dependency."""
import re
import unicodedata
from datetime import datetime
from decimal import Decimal


def normalize(text):
    text = unicodedata.normalize('NFKD', str(text))
    return ''.join(c for c in text if not unicodedata.combining(c)).upper().strip().rstrip(':').strip()


def number(text):
    value = re.sub(r'(?:EUR|MAD|DH|€)\s*$', '', str(text).strip(), flags=re.I)
    value = ''.join(value.split()).replace(',', '.')
    if not re.fullmatch(r'\d+(?:\.\d+)?', value) or len(value) > 20:
        raise ValueError('Unsupported numeric value: ' + str(text))
    return Decimal(value)


def extract_fields(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    def unique(pattern):
        values = [m.group(1).strip() for line in lines if (m := re.fullmatch(pattern, line, re.I))]
        return values[0] if len(values) == 1 else None
    def amount(label):
        values = []
        for i, line in enumerate(lines):
            match = re.fullmatch(label + r'\s*:?\s*(.*)', normalize(line), re.I)
            if match:
                candidate = match.group(1) or (lines[i+1] if i+1 < len(lines) else '')
                try:
                    values.append(format(number(candidate), '.2f'))
                except ValueError:
                    values.append(None)
        return values[0] if len(values) == 1 else None
    raw_date = unique(r'Date\s*:\s*(\d{2}\s*/\s*\d{2}\s*/\s*\d{4})')
    try:
        invoice_date = datetime.strptime(re.sub(r'\s', '', raw_date or ''), '%d/%m/%Y').date().isoformat()
    except ValueError:
        invoice_date = None
    currencies = set()
    for line in lines:
        if re.search(r'€|\bEUR\b', line, re.I): currencies.add('EUR')
        if re.search(r'\b(?:MAD|DH)\b', line, re.I): currencies.add('MAD')
        explicit = re.fullmatch(r'Devise\s*:\s*([A-Z]{3})', line, re.I)
        if explicit: currencies.add(explicit.group(1).upper())
    return {
        'invoice_number': unique(r'(?:FACTURE\s*)?N[°º]\s*:?\s*([A-Z0-9][A-Z0-9/\-]*)'),
        'invoice_date': invoice_date,
        'currency': next(iter(currencies)) if len(currencies) == 1 else None,
        'subtotal': amount(r'TOTAL\s+HT'),
        'tax_amount': amount(r'TVA(?:\s*\(?\s*\d+(?:[,.]\d+)?\s*%\s*\)?)?'),
        'total': amount(r'TOTAL\s+TTC'),
    }


def extract_items(text):
    lines = [s.strip() for s in text.splitlines() if s.strip()]
    labels = {'DESCRIPTION': 'description', 'DESIGNATION': 'description',
              'QUANTITE': 'quantity', 'PRIX UNITAIRE': 'unit_price',
              'PRIX UNITAIRE HT': 'unit_price', 'MONTANT HT': 'line_total', 'TOTAL': 'line_total'}
    headers = [(i, labels[normalize(s)]) for i, s in enumerate(lines) if normalize(s) in labels]
    ends = [i for i,s in enumerate(lines) if re.match(r'^TOTAL\s+HT(?:\s|:|$)', normalize(s))]
    try:
        if len(headers) != 4 or len({key for _,key in headers}) != 4 or len(ends) != 1:
            raise ValueError('Cannot identify four unique table columns and one Total HT boundary.')
        if [i for i,_ in headers] != list(range(headers[0][0], headers[0][0]+4)):
            raise ValueError('Table headings are not consecutive; review layout.')
        start, end = headers[-1][0]+1, ends[0]
        if end <= start: raise ValueError('No table rows detected.')
        values = lines[start:end]
        if len(values) % 4: raise ValueError('Table rows do not contain four separate OCR values.')
        items = []
        for offset in range(0,len(values),4):
            row = dict(zip([key for _,key in headers], values[offset:offset+4]))
            if all(v.strip() in {'-', '—', '–'} for v in row.values()): continue
            for key in ('quantity','unit_price','line_total'):
                n = number(row[key])
                if key == 'quantity' and n <= 0: raise ValueError('Quantity must be positive.')
                if key != 'quantity' and n != n.quantize(Decimal('0.01')):
                    raise ValueError('Amount has more than two decimals; review required.')
                row[key] = str(n) if key == 'quantity' else format(n, '.2f')
            items.append(row)
        if not items: raise ValueError('No complete items detected.')
        return {'items': items, 'extraction_status': 'EXTRACTED', 'warnings': []}
    except ValueError as error:
        return {'items': [], 'extraction_status': 'NEEDS_REVIEW', 'warnings': [str(error)]}


def extract_parties(data):
    data = data.get('res', data)
    texts, boxes = data['rec_texts'], data['rec_boxes']
    if len(texts) != len(boxes): raise ValueError('Text and coordinate counts differ.')
    def below(aliases):
        indices = [i for i,t in enumerate(texts) if normalize(t) in aliases]
        if len(indices) != 1: return None
        left, top, right, bottom = boxes[indices[0]]
        height = max(bottom-top,1)
        candidates = []
        for text, (x1,y1,x2,y2) in zip(texts,boxes):
            gap = y1-bottom
            aligned = min(abs(x1-left),abs(x2-right)) <= 3*height
            if 0 <= gap <= 4*height and aligned and text.strip(): candidates.append((gap,text.strip()))
        if not candidates: return None
        candidates.sort()
        candidate = candidates[0][1]
        # Never turn an identifier, contact line or street address into a party name.
        if not re.search(r'[^\W\d_]', candidate, re.UNICODE): return None
        if re.match(r'^\d',candidate) or '@' in candidate or re.search(r'https?://|www\.',candidate,re.I): return None
        return candidate
    return {'supplier_name': below({'FOURNISSEUR','EMETTEUR'}),
            'customer_name': below({'CLIENT','DESTINATAIRE'})}

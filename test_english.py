import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import english_layout as parser

ROOT=Path(__file__).resolve().parent
class EnglishTests(unittest.TestCase):
    def setUp(self): self.data=json.loads((ROOT/'test_data/english_ocr.json').read_text())
    def test_headers_and_discount(self):
        f=parser.fields(self.data)
        for key,value in dict(invoice_number='INV/20111209-22',invoice_date='2011-12-08',currency='EUR',subtotal='835.00',tax_amount='150.30',discount_amount='83.50',total='901.80').items(): self.assertEqual(f[key],value)
        self.assertEqual(parser.parties(self.data),dict(supplier_name='RedmineCRM',customer_name='"Romashka" Ltd.'))
    def test_all_item_values_and_continuations(self):
        rows=parser.items(self.data)['items'];self.assertEqual(len(rows),3)
        for r,expected in zip(rows,[('1.0','50.00','50.00'),('17.0','40.00','680.00'),('3.0','35.00','105.00')]):
            self.assertEqual(tuple(r[k] for k in ['quantity','unit_price','line_total']),expected)
        self.assertEqual(len(rows[1]['description'].splitlines()),5)
        self.assertEqual(rows[2]['description'],'Analysis\n- [PRO] Duplicating invoices\n- Language support')
    def test_ambiguous_date_not_guessed(self):
        d=self.data.get('res',self.data)
        d['rec_texts']=[t.replace('12/25/2012','12/11/2012') for t in d['rec_texts']]
        self.assertIsNone(parser.fields(self.data)['invoice_date'])
    def test_missing_numeric_cell_requires_review(self):
        d=self.data.get('res',self.data);i=d['rec_texts'].index('680.00');d['rec_texts'].pop(i);d['rec_boxes'].pop(i)
        self.assertEqual(parser.items(self.data)['extraction_status'],'NEEDS_REVIEW')
    def test_actual_ocr_pipeline_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for p in ROOT.glob('*.py'):shutil.copy(p,root/p.name)
            out=root/'outputs';out.mkdir();(root/'sample.png').write_bytes(b'OCR intentionally bypassed')
            (out/'sample_res.json').write_text(json.dumps(self.data))
            d=self.data.get('res',self.data)
            (out/'sample_text.txt').write_text('\n'.join(d['rec_texts']),encoding='utf-8')
            r=subprocess.run([sys.executable,str(root/'run_pipeline.py'),'sample.png','--skip-ocr'],capture_output=True,text=True,encoding='utf-8',env={**os.environ,'PYTHONUTF8':'1'})
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            result=json.loads((out/'sample_structured.json').read_text())
            self.assertEqual(result['total'],'901.80');self.assertEqual(len(result['items']),3)
            for suffix in ['structured_checks','items_checks']:
                self.assertEqual(json.loads((out/f'sample_{suffix}.json').read_text())['status'],'PASS')
if __name__=='__main__': unittest.main()

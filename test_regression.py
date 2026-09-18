"""Run with python -m unittest -v test_regression. No PaddleOCR required.
Fixtures reproduce observed text; coordinate fixtures are synthetic, not OCR measurements.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from invoice_parsing import extract_fields, extract_items, extract_parties

EUR_TEXT = '''FACTURE
nomade
STUDIO CREATIF
DATE:30/10/2035
ÉCHÉANCE:30/11/2035
FACTUREN°:123-456-7890
ÉMETTEUR:
DESTINATAIRE:
123-456-7890
M.NOA ANDRIEUX
hello@reallygreatsite.com
Description:
Prix Unitaire :
Quantité :
Total :
Identité visuelle
2500,00€
1
2500,00€
Rapport détaillé
1500,00€
1
1500,00€
Formation des équipes
1200,00€
1
1200,00€
TOTAL HT:
5200,00€
TVA 20%:
1040,00€
RÈGLEMENT :
REMISE:
Par virement bancaire :
Banque : Rimberio
TOTAL TTC:
6240,00€'''

def mad(second=False):
    rows = [('Lampe de bureau','3','175,50','526,50'),('Cahier A4','10','32,40','324,00'),('Support ecran','2','225,00','450,00')] if second else [('Clavier USB','4','150,00','600,00'),('Souris optique','5','80,00','400,00'),('Support ordinateur','2','250,00','500,00')]
    return '\n'.join(['Date : '+('19/09/2026' if second else '18/09/2026'), 'N° FAC-DEMO-00'+('2' if second else '1'),'Devise : MAD','Désignation','Quantité','Prix unitaire HT','Montant HT',*[v for row in rows for v in row],'Total HT',('1 300,50' if second else '1 500,00')+' MAD','TVA (20 %)',('260,10' if second else '300,00')+' MAD','TOTAL TTC',('1 560,60' if second else '1 800,00')+' MAD'])

class ExtractionTests(unittest.TestCase):
    def test_eur_fields(self):
        self.assertEqual(extract_fields(EUR_TEXT), dict(invoice_number='123-456-7890', invoice_date='2035-10-30', currency='EUR',subtotal='5200.00',tax_amount='1040.00',total='6240.00'))
    def test_mad_samples(self):
        for second,total in [(False,'1800.00'),(True,'1560.60')]:
            fields=extract_fields(mad(second)); self.assertTrue(all(fields.values())); self.assertEqual(fields['total'],total)
            rows=extract_items(mad(second))['items']; self.assertEqual(len(rows),3)
            self.assertEqual(rows[0]['quantity'],'3' if second else '4')
    def test_price_before_quantity(self):
        rows=extract_items(EUR_TEXT)['items']; self.assertEqual(len(rows),3)
        self.assertEqual(rows[0],dict(description='Identité visuelle',quantity='1',unit_price='2500.00',line_total='2500.00'))
    def test_bad_table_is_reviewable(self):
        for text in [EUR_TEXT.replace('Total :','Unknown :'),EUR_TEXT.replace('2500,00€\n1','2500,00€\nextra\n1'), '']:
            result=extract_items(text); self.assertEqual(result['items'],[]); self.assertTrue(result['warnings'])
    def test_ambiguity(self):
        self.assertIsNone(extract_fields(EUR_TEXT+'\nDevise: MAD')['currency'])
        self.assertIsNone(extract_fields(EUR_TEXT+'\nTOTAL TTC:\n6240,00€')['total'])
    def test_invalid_date(self):
        self.assertIsNone(extract_fields(EUR_TEXT.replace('30/10/2035','30/02/2035'))['invoice_date'])
    def test_parties_synthetic_coordinates(self):
        data=dict(rec_texts=['ÉMETTEUR:','DESTINATAIRE:','123-456-7890','M.NOA ANDRIEUX'],rec_boxes=[[10,10,70,20],[200,10,280,20],[10,25,90,35],[190,25,280,35]])
        self.assertEqual(extract_parties(data),dict(supplier_name=None,customer_name='M.NOA ANDRIEUX'))
        data['rec_texts']=['FOURNISSEUR','CLIENT','Atlas Bureau Demo','Riad Horizon Demo']
        self.assertEqual(extract_parties({'res':data}),dict(supplier_name='Atlas Bureau Demo',customer_name='Riad Horizon Demo'))
    def test_pipeline_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for file in Path(__file__).parent.glob('*.py'): shutil.copy(file,root/file.name)
            (root/'outputs').mkdir(); (root/'sample.png').write_bytes(b'placeholder: OCR intentionally skipped')
            for source in [mad(),mad(True),EUR_TEXT,EUR_TEXT.replace('Total :','Unknown :')]:
                (root/'outputs/sample_text.txt').write_text(source,encoding='utf-8')
                (root/'outputs/sample_res.json').write_text(json.dumps(dict(rec_texts=[],rec_boxes=[])))
                result=subprocess.run([sys.executable,str(root/'run_pipeline.py'),str(root/'sample.png'),'--skip-ocr'],capture_output=True,text=True,encoding='utf-8',env={**os.environ,'PYTHONUTF8':'1'})
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                final=json.loads((root/'outputs/sample_structured.json').read_text())
                check=json.loads((root/'outputs/sample_items_checks.json').read_text())
                self.assertEqual(check['status'],'NEEDS_REVIEW' if 'Unknown' in source else 'PASS')
                self.assertIn('items',final)

if __name__ == '__main__': unittest.main()

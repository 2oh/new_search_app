from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'tools'))
import composite_catalog as catalog
import composite_stock as stock
from composite_export import export_parts
from composite_fixture import create
import pdf_catalog
from openpyxl import load_workbook


class CompositeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root/'bom.sqlite'
        create(self.database, self.root/'books')
        self.catalog = catalog.Catalog(self.database)

    def test_row_filters_and_representative(self):
        all_groups = self.catalog.search()
        ss = next(g for g in all_groups if g['identifier'] == 'U123' and g['material'] == 'SS400')
        self.assertEqual(ss['name'], 'ブラケット')  # 2 products vs 1 product with 3 rows
        filtered = self.catalog.search(ids='1002', contains='取付金具')
        self.assertEqual(filtered[0]['name'], 'ブラケット')
        self.assertEqual({o['product_id'] for o in filtered[0]['occurrences']}, {'1002'})
        self.assertEqual(self.catalog.search(contains='取付金具 ブラケット'), [])
        self.assertEqual(len([g for g in all_groups if not g['identifier']]), 2)
        self.assertEqual(len(self.catalog.search(ids='0001', contains='A5052')), 1)
        arrow = self.catalog.search(ids='0001', contains='A5052')[0]
        self.assertEqual((arrow['identifier'], arrow['keyword']), ('U123', '123'))
        self.assertEqual(len(self.catalog.search(ids='0001', contains='U123')), 2)
        self.assertNotEqual(arrow['key'], ss['key'])
        self.assertEqual(len(self.catalog.search(ids='0001,1002', folders=['タイプA'], sheets=['架台'], excludes='A5052')), 2)
        self.assertEqual({o['product_id'] for g in self.catalog.search(start='2026-11-11',end='2026-11-11') for o in g['occurrences']}, {'0001'})
        with self.assertRaises(ValueError): self.catalog.search(ids='1')
        with self.assertRaises(ValueError): self.catalog.search(start='2026-12-01',end='2026-11-01')
        self.assertTrue(any(o['product_id'] == '' for g in all_groups for o in g['occurrences']))

    def test_stock_pdf_links_and_atomic_export(self):
        paths = [self.root/'123 first.pdf', self.root/'123 second.pdf']
        groups = catalog.attach_pdfs(self.catalog.search(ids='0001', contains='SS400'), paths)
        items = stock.add([], groups)
        items = stock.add(items, catalog.attach_pdfs(self.catalog.search(ids='1002',contains='取付金具'), paths))
        self.assertEqual(len(items), 1)
        self.assertEqual({o['product_id'] for o in items[0]['occurrences']}, {'0001','1002'})
        self.assertEqual(len(items[0]['pdfs']), 2)
        filename = self.root/'part_stock.json'
        stock.save(filename, items)
        self.assertEqual(stock.load(filename), items)
        target = self.root/'output.xlsx'
        items[0]['name'] = '=test'
        export_parts(items, target)
        with target.open('rb') as stream:
            wb = load_workbook(stream)
            sheet = wb.active
            self.assertEqual(sheet.max_row, 3)
            self.assertEqual(sheet['A2'].data_type, 's')
            self.assertEqual(sheet['A2'].value, '=test')
            self.assertIsNone(sheet['A3'].value)
            self.assertEqual(sheet['E2'].value, '0001, 1002')
            self.assertEqual(sheet['D3'].hyperlink.target, paths[1].as_uri())
            wb.close()
        previous = target.read_bytes()
        with patch('composite_export.os.replace', side_effect=OSError('disk')):
            with self.assertRaises(OSError): export_parts(items, target)
        self.assertEqual(previous, target.read_bytes())
        self.assertFalse(list(self.root.glob('.parts-*')))
        self.assertEqual(stock.add(items, groups)[0]['name'], groups[0]['name'])

    def test_sync_keeps_previous_on_failure(self):
        folder = self.root/'publish'
        folder.mkdir()
        name = 'catalog-' + 'a'*32 + '.sqlite'
        data = folder/name
        data.write_bytes(self.database.read_bytes())
        manifest = dict(file=name, sha256=pdf_catalog.digest(data),size=data.stat().st_size,updated=catalog.metadata(data)['updated'])
        pdf_catalog.save_json(folder/'latest.json', manifest)
        local = self.root/'local.sqlite'
        self.assertTrue(catalog.sync(folder,local))
        self.assertFalse(catalog.sync(folder,local))
        previous = local.read_bytes()
        data.write_bytes(b'broken')
        local.unlink()
        local.write_bytes(previous + b' ')  # force a transfer
        old = local.read_bytes()
        with self.assertRaises(ValueError): catalog.sync(folder,local)
        self.assertEqual(local.read_bytes(), old)
        manifest['file'] = '../outside.sqlite'
        pdf_catalog.save_json(folder/'latest.json',manifest)
        with self.assertRaises(ValueError): catalog.sync(folder,local)


if __name__ == '__main__':
    unittest.main()

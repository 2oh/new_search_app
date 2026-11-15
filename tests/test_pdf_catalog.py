import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import pdf_catalog as catalog
from normal_search import parse_search_query, search_files
from pdf_index_batch import main as batch_main


class PdfCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / '日本語 PDF'
        self.root.mkdir()
        self.database = self.base / 'index.sqlite'
        self.public = self.base / '公開'
        self.local = self.base / 'client' / 'index.sqlite'
        for index, name in enumerate(['a/Ｆ123 SS400.pdf', 'a/F123 ss400 newer.pdf',
                                      'b/F123 SS400.pdf', 'b/err  pp .PDF', 'not-a-pdf.txt']):
            path = self.root / name
            path.parent.mkdir(exist_ok=True)
            path.write_text('fixture', encoding='utf-8')
            os.utime(path, (1700000000 + index, 1700000000 + index))

    def build(self):
        catalog.ingest(self.root, self.database)
        return catalog.publish(self.database, self.public)

    def test_matches_existing_search_and_order(self):
        self.build()
        files = list(self.root.rglob('*.[pP][dD][fF]'))
        for query in ['f123', 'Ｆ123 ss400', '"F123 SS400"', 'err / pp ', 'pdf', '', 'b', 'none']:
            words = parse_search_query(query)
            expected = search_files(words, files)
            actual = catalog.search(self.database, words)[1]
            self.assertEqual(expected, actual, query)

    def test_search_offline_and_generation_changes(self):
        self.build()
        catalog.sync(self.public, self.local)
        old = catalog.search(self.local, ['f123'])[1]
        hidden = self.base / 'offline'
        self.root.rename(hidden)
        # Results remain available without checking the source filesystem.
        self.assertEqual(old, catalog.search(self.local, ['f123'])[1])
        hidden.rename(self.root)
        (self.root / 'a/F123 ss400 newer.pdf').unlink()
        (self.root / 'a/Ｆ123 SS400.pdf').rename(self.root / 'b/renamed.pdf')
        (self.root / 'a/new.pdf').write_bytes(b'new')
        self.build()
        self.assertEqual(old, catalog.search(self.local, ['f123'])[1])
        self.assertTrue(catalog.sync(self.public, self.local))
        self.assertEqual(1, len(catalog.search(self.local, ['f123'])[1]))
        self.assertEqual(1, len(catalog.search(self.local, ['new'])[1]))
        self.assertFalse(catalog.sync(self.public, self.local))

    def test_snapshot_preserves_order_and_is_offline(self):
        self.build()
        expected = []
        for folder, _, names in os.walk(self.root):
            expected.extend(Path(folder) / name for name in names if name.lower().endswith('.pdf'))
        info, paths = catalog.snapshot_paths(self.database)
        self.assertEqual(expected, paths)
        self.assertEqual(str(self.root), info['root'])
        self.root.rename(self.base / 'offline')
        self.assertEqual((info, paths), catalog.snapshot_paths(self.database))

    def test_unavailable_empty_and_partial_scan_preserve_database(self):
        self.build()
        before = self.database.read_bytes()
        with self.assertRaises(FileNotFoundError):
            catalog.ingest(self.base / 'missing', self.database)
        empty = self.base / 'empty'
        empty.mkdir()
        with self.assertRaises(ValueError):
            catalog.ingest(empty, self.database)
        def broken_walk(root, onerror, **kwargs):
            yield str(self.root / 'a'), [], ['Ｆ123 SS400.pdf']
            onerror(PermissionError('denied'))
        with patch.object(catalog.os, 'walk', side_effect=broken_walk):
            with self.assertRaises(PermissionError):
                catalog.ingest(self.root, self.database)
        self.assertEqual(before, self.database.read_bytes())
        self.assertFalse(list(self.base.glob('.pdf-build-*')))

    def test_corrupt_transfer_preserves_local(self):
        self.build()
        catalog.sync(self.public, self.local)
        before = self.local.read_bytes()
        manifest = self.build()
        (self.public / manifest['file']).write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            catalog.sync(self.public, self.local)
        self.assertEqual(before, self.local.read_bytes())
        self.assertFalse(list(self.local.parent.glob('.pdf-sync-*')))

    def test_publish_failure_preserves_manifest(self):
        self.build()
        before = (self.public / catalog.MANIFEST).read_bytes()
        with patch.object(catalog, 'save_json', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                catalog.publish(self.database, self.public)
        self.assertEqual(before, (self.public / catalog.MANIFEST).read_bytes())
        self.assertEqual(1, len(list(self.public.glob('pdf-catalog-*.sqlite'))))

    def test_bad_schema_and_manifest_cannot_replace_local(self):
        self.build()
        catalog.sync(self.public, self.local)
        before = self.local.read_bytes()
        manifest = self.build()
        target = self.public / manifest['file']
        with sqlite3.connect(target) as db:
            db.execute("UPDATE metadata SET value='999' WHERE key='schema'")
        db.close()
        manifest['sha256'] = catalog.digest(target)
        manifest['size'] = target.stat().st_size
        catalog.save_json(self.public / catalog.MANIFEST, manifest)
        with self.assertRaises(ValueError):
            catalog.sync(self.public, self.local)
        manifest['file'] = '../escape.sqlite'
        catalog.save_json(self.public / catalog.MANIFEST, manifest)
        with self.assertRaises(ValueError):
            catalog.sync(self.public, self.local)
        self.assertEqual(before, self.local.read_bytes())

    def test_batch_relative_paths_and_failure_exit(self):
        config = self.base / 'batch.json'
        catalog.save_json(config, {'root': str(self.root), 'database': 'batch/index.sqlite',
                                  'publish': 'batch/publish', 'logs': 'batch/logs'})
        self.assertEqual(0, batch_main(['--config', str(config)]))
        manifest_path = self.base / 'batch/publish' / catalog.MANIFEST
        before = manifest_path.read_bytes()
        self.root.rename(self.base / 'not-connected')
        self.assertEqual(1, batch_main(['--config', str(config)]))
        self.assertEqual(before, manifest_path.read_bytes())

    def test_lock_and_initial_missing_database(self):
        with catalog.operation_lock(self.base / 'update.lock'):
            with self.assertRaises(RuntimeError):
                with catalog.operation_lock(self.base / 'update.lock'):
                    pass
        with self.assertRaises(FileNotFoundError):
            catalog.search(self.local, ['f123'])


if __name__ == '__main__':
    unittest.main()

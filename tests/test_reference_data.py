import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import pdf_catalog
from reference_data import PublicationCheck, ReferenceData
from tools.composite_demo import select_demo


class ReferenceTests(unittest.IsolatedAsyncioTestCase):
    def test_publication_states_and_persistent_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = select_demo(root)
            stock = first/'part_stock.json'
            stock.write_text('preserve me')
            assert select_demo(root) == first
            assert stock.read_text() == 'preserve me'
            publication = first/'配信元'
            local = first/'local.pdf.sqlite'
            checker = PublicationCheck()
            assert checker.inspect(publication, local, 'pdf')['state'] == 'pending'
            pdf_catalog.sync(publication, local)
            assert checker.inspect(publication, local, 'pdf')['state'] == 'current'
            with patch('reference_data.pdf_catalog.digest', side_effect=AssertionError('rehashed unchanged DB')):
                assert checker.inspect(publication, local, 'pdf')['state'] == 'current'
            before = local.read_bytes()
            manifest = json.loads((publication/'pdf-latest.json').read_text())
            manifest['sha256'] = 'a'*64
            pdf_catalog.save_json(publication/'pdf-latest.json', manifest)
            assert checker.inspect(publication, local, 'pdf')['state'] == 'pending'
            assert local.read_bytes() == before
            assert checker.inspect(root/'offline', local, 'pdf')['state'] == 'unknown'
            assert checker.inspect(root/'offline', local, 'pdf')['count'] == 21
            second = select_demo(root,new=True)
            assert second != first and stock.read_text() == 'preserve me'
            assert select_demo(root) == second

    async def test_button_states_and_stale_path_response(self):
        import flet as ft
        page = SimpleNamespace(update=lambda: None)
        normal = SimpleNamespace(sync_button=ft.Button('取得'), busy=lambda:False,
            publish_field=SimpleNamespace(value='first'), index_database='pdf')
        composite = SimpleNamespace(database='bom')
        panel = ReferenceData(page,normal,composite,None)
        current = dict(state='current',updated='',count=3,error='')
        panel.states = [dict(current),dict(current)]
        panel.render()
        assert normal.sync_button.disabled
        panel.states[1]['state']='pending'
        panel.render()
        assert not normal.sync_button.disabled
        panel.set_mode('構成部品表')
        assert panel.texts[1].value == '原本直接参照'
        panel.invalidate()
        assert not normal.sync_button.disabled
        def inspect(*args):
            normal.publish_field.value='second'
            return dict(current)
        with patch.object(panel.checker,'inspect',side_effect=inspect):
            await panel.refresh()
        assert all(s['state']=='unknown' for s in panel.states)

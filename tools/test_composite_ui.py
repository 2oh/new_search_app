"""Real Flet control/session regression without native Excel or live network paths."""
import asyncio
from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import AsyncMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_ui_state import load
from composite_fixture import create


async def exercise(scope, destination):
    import composite_catalog
    import pdf_catalog
    composite = scope['composite_mode']
    normal = scope['normal_mode']
    normal.focus = AsyncMock()
    composite.database = destination/'composite.sqlite'
    create(composite.database, destination/'books')
    normal.index_database = destination/'pdf.sqlite'
    pdfs = destination/'pdfs'
    pdfs.mkdir(exist_ok=True)
    import fitz
    for name in ('123 first.pdf','123 second.pdf'):
        with fitz.open() as document:
            document.new_page().insert_text((72,72),name)
            document.save(pdfs/name)
    pdf_catalog.ingest(pdfs,normal.index_database)
    normal.refresh_index_label()
    scope['mode_dropdown'].value = '複合'
    scope['on_mode_change'](None)
    assert composite.view.visible and not normal.view.visible and not scope['result_area'].visible
    assert [o.key for o in scope['mode_dropdown'].options] == ['PDFファイル名','複合','構成部品表']
    composite.ids.value = '0001'
    composite.query.value = 'SS400'
    await composite.search()
    assert len(composite.results) == 1, scope['message'].value
    group = composite.results[0]
    assert len(group['pdfs']) == 2 and group['name'] == 'ブラケット'
    await composite.select_all()
    await composite.add_selected()
    assert len(composite.items) == 1 and not normal.items
    composite.ids.value = '1002'
    composite.query.value = '取付金具'
    await composite.search()
    await composite.select_all()
    await composite.add_selected()
    assert len(composite.items) == 1
    assert {o['product_id'] for o in composite.items[0]['occurrences']} == {'0001','1002'}
    await composite.show_candidates(group)
    assert composite.preview_panel.visible and composite.image.visible
    before = deepcopy(composite.items)
    selection = set(composite.selection)
    composite.toggle_preview()
    assert not composite.preview_panel.visible and composite.items == before and composite.selection == selection
    composite.toggle_preview()
    composite.pdf_selection.add(group['pdfs'][1])
    await composite.add_pdfs()
    assert len(normal.items) == 1 and normal.items[0]['path'] == group['pdfs'][1]
    composite.show_stock()
    scope['output_folder_field'].value = str(destination)
    await composite.export()
    assert list(destination.glob('部品一覧_*.xlsx')), scope['message'].value
    with patch.object(composite.launcher, 'launch_url', new_callable=AsyncMock) as open_mock:
        await composite.open_occurrence(group['occurrences'][0])
        open_mock.assert_awaited_once()
        assert open_mock.call_args.args[0].endswith('.lnk')
    await composite.choose_sheets()
    scope['page'].pop_dialog()
    # Selection is the entire model, not the current viewport.
    composite.stock_view = False
    composite.results = [dict(group,key=str(i)) for i in range(1500)]
    await composite.select_all()
    assert len(composite.selection) == 1500 and len(composite.list.controls) == 1500
    normal.index_database = destination/'missing.sqlite'
    await composite.search()
    assert composite.results[0]['pdf_status'] == 'PDF索引未取得'
    # The BOM snapshot must still arrive when the PDF publication is absent.
    publication = destination/'publication'
    publication.mkdir()
    name = 'catalog-' + 'b'*32 + '.sqlite'
    published = publication/name
    published.write_bytes(composite.database.read_bytes())
    pdf_catalog.save_json(publication/'latest.json', dict(file=name, sha256=pdf_catalog.digest(published),
        size=published.stat().st_size, updated=composite_catalog.metadata(published)['updated']))
    before_stock = deepcopy(composite.items)
    composite.database = destination/'received-bom.sqlite'
    normal.publish_field.value = str(publication)
    await normal.sync_index()
    assert composite.database.exists() and composite.items == before_stock
    assert '取得失敗' not in composite.index_label.value and '失敗' in normal.index_label.value
    assert not composite.results
    normal.publish_field.value = ''
    assert not composite.normal.busy()
    scope['mode_dropdown'].value = '構成部品表'
    scope['on_mode_change'](None)
    assert scope['result_area'].visible and not composite.view.visible
    return ['composite grouping and filters', 'part stock persistence', 'multiple PDF links',
            'preview toggle', 'PDF stock bridge', '1500 parts select all', 'source sheet dispatch']


async def run():
    root = Path(__file__).resolve().parents[1]
    app = load('composite_test_app',root/'main.py')
    helper = load('composite_test_helper',root/'tools/frozen_selftest.py')
    with tempfile.TemporaryDirectory(prefix='composite-ui-') as directory:
        previous = Path.cwd()
        os.chdir(directory)
        session = helper.Session(helper.MemoryConnection())
        session.start_updates_scheduler()
        session.get_page_patch()
        token = helper._context_page.set(session.page)
        scope = {}
        old = sys.getprofile()
        def capture(frame,event,arg):
            if event == 'return' and frame.f_code is app.main.__code__:
                scope.update(frame.f_locals)
        try:
            sys.setprofile(capture)
            app.main(session.page)
            sys.setprofile(old)
            print('PASS:', await exercise(scope,Path(directory)))
        finally:
            sys.setprofile(old)
            session.close()
            helper._context_page.reset(token)
            os.chdir(previous)


if __name__ == '__main__':
    asyncio.run(run())

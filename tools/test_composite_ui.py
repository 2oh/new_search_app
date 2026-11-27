"""Real Flet control/session regression without native Excel or live network paths."""
import asyncio
from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
import threading
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_ui_state import load
from composite_fixture import create


async def exercise(scope, destination):
    import composite_catalog
    import pdf_catalog
    composite = scope['composite_mode']
    composite.key_target.focus = AsyncMock()
    composite.list.scroll_to = AsyncMock()
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
    assert not composite.preview_panel.visible and not composite.preview_hint.visible
    assert composite.tabs.selected_index == 0
    group = composite.results[0]
    assert len(group['pdfs']) == 2 and group['name'] == 'ブラケット'
    normal.query.value = '123'
    await normal.search()
    assert len(normal.results) == 2
    sample = pdfs / 'タイプA' / '試作'
    sample.mkdir(parents=True)
    (sample / '123 extra.pdf').touch()
    bulk = pdfs / 'タイプB'
    bulk.mkdir()
    for index in range(498):
        (bulk / f'extra123-{index}.pdf').touch()
    pdf_catalog.ingest(pdfs, normal.index_database)
    await normal.search()
    assert '500件を超えました' in normal.message.value
    assert not normal.results and not normal.result_table.rows and normal.match_count == 501
    dialog = scope['page']._dialogs.controls[-1]
    count, listing = dialog.content.content.controls[1:]
    assert dialog.open and dialog.actions[-1].disabled and '501件' in count.value
    assert [row.controls[3].value for row in listing.controls] == ['（検索先直下）', 'タイプA', 'タイプB']
    listing.controls[1].controls[1].on_click(None)
    child = listing.controls[2].controls[2]
    child.value = True
    child.on_change(SimpleNamespace(control=child))
    assert not dialog.actions[-1].disabled and count.value == '対象 1件'
    dialog.actions[-1].on_click(None)
    assert not dialog.open and len(normal.results) == 1 and len(normal.result_table.rows) == 1
    normal.select_all()
    hidden = set(normal.selection)
    normal.apply_folder_filter({()})
    normal.select_all()
    assert len(normal.selection - hidden) == 2 and '非表示のチェック 1件' in normal.result_count.value
    with patch.object(normal, 'commit', new_callable=AsyncMock) as commit:
        await normal.add_selected()
        assert {i['path'] for i in commit.call_args.args[0]} == {i['path'] for i in normal.results}
    normal.invert_results()
    assert normal.selection == hidden
    normal.apply_folder_filter({(), ('タイプB',)})
    assert len(normal.results) == 500
    for path in (*bulk.glob('*.pdf'), *sample.glob('*.pdf')):
        path.unlink()
    pdf_catalog.ingest(pdfs, normal.index_database)
    model = composite.catalog
    baseline_rows = model.rows
    matching = next(row for row in baseline_rows if row['key'] == group['key'] and row['eligible'])
    model.rows = [dict(matching, key=str(index)) for index in range(301)]
    with patch.object(composite_catalog, 'attach_pdfs') as attach:
        await composite.search()
        attach.assert_not_called()
    assert '300部品を超えました' in normal.message.value
    assert composite.results == [group]
    model.rows = [*model.rows[:300], matching | {'key': '0', 'row_number': matching['row_number'] + 1}]
    groups = model.search(contains='SS400', ids='0001', max_results=300)
    assert len(groups) == 300 and len(next(g for g in groups if g['key'] == '0')['occurrences']) == 2
    model.rows = baseline_rows
    await composite.select_all()
    await composite.add_selected()
    assert len(composite.items) == 1 and not normal.items
    # Same vehicle/sheet in different workbooks must remain separate links.
    original = group['occurrences'][0]
    different = dict(original,path=str(destination/'other.xlsx'))
    assy, _ = composite.assy_cell(dict(group,occurrences=[original,dict(original),different]), True)
    labels = assy.content.controls[0].content.controls[1].controls[0].controls
    assert len(labels)==2 and labels[0].tooltip != labels[1].tooltip
    assert labels[0].tooltip.splitlines()[2].startswith('更新日時：2026-11-11 '), labels[0].tooltip
    source = Path(original['path'])
    assert labels[0].tooltip.splitlines()[:2] == [f'構成部品表パス：{source.parent.name}', f'ファイル名：{source.name}']
    with patch.object(composite, 'open_occurrence', new_callable=AsyncMock) as opened:
        await labels[1].on_click(None)
        assert opened.call_args.args[0]['path']==different['path']
    composite.ids.value = '1002'
    composite.query.value = '取付金具'
    await composite.search()
    await composite.select_all()
    await composite.add_selected()
    assert len(composite.items) == 1
    assert {o['product_id'] for o in composite.items[0]['occurrences']} == {'0001','1002'}
    await composite.show_candidates(group)
    assert composite.preview_panel.visible and composite.image.visible
    assert composite.preview_button.content == 'PDFプレビューを閉じる'
    assert 'Esc 閉じる' in composite.preview_hint.value
    assert scope['mode_row'].disabled and scope['folder_settings_row'].disabled
    assert composite.filters.disabled and composite.tab_bar.disabled and composite.list_panel.disabled
    assert all(action.disabled for action in composite.list_actions)
    assert not any(action.visible for action in composite.list_actions)
    assert not composite.preview_button.disabled and not composite.candidates.disabled
    assert await scope['input_focus'].restore_preferred_focus()
    overlay = scope['preview_focus_overlay']
    assert overlay.visible
    composite.key_target.focus.reset_mock()
    await overlay.on_tap(None)
    composite.key_target.focus.assert_awaited_once()
    assert composite.preview_panel.width > min(660, max(370, (scope['page'].width or 1400) * .35))
    composite.tabs.selected_index = 1
    composite.on_tab_change()
    assert composite.preview_panel.visible and composite.tabs.selected_index == 0
    await composite.search()
    assert not composite.preview_panel.visible and composite.active_key is None
    assert not scope['mode_row'].disabled and not composite.filters.disabled and not composite.list_panel.disabled
    assert not overlay.visible
    composite.key_target.focus.reset_mock()
    await overlay.on_tap(None)
    composite.key_target.focus.assert_not_awaited()
    assert composite.preview_button.content == 'PDFプレビューを表示'
    await composite.show_candidates(group)
    before = deepcopy(composite.items)
    selection = set(composite.selection)
    assert composite.toolbar_actions.controls[-2:] == [composite.preview_hint, composite.preview_button]
    assert all(c.style == scope['BUTTON_STYLE_SECONDARY'] for c in composite.list_actions[:3])
    assert composite.add_button.style == scope['BUTTON_STYLE_PRIMARY']
    composite.navigation_focused = False
    await scope['page'].on_keyboard_event(SimpleNamespace(key='Escape'))
    assert not composite.preview_panel.visible and composite.items == before and composite.selection == selection
    assert all(action.visible for action in composite.list_actions[:3]) and composite.add_button.visible
    assert not composite.remove_button.visible and not composite.export_button.visible
    await composite.show_candidates(group)
    original_stock = deepcopy(normal.items)
    assert composite.candidate_index == 0 and not composite.navigating_candidates
    await composite.navigate_key(SimpleNamespace(key='Arrow Right'))
    assert composite.navigating_candidates
    await composite.navigate_key(SimpleNamespace(key='ArrowDown'))
    assert composite.active_key == group['key'] and composite.candidate_index == 1
    assert composite.preview_label.value == Path(group['pdfs'][1]).name
    await composite.navigate_key(SimpleNamespace(key='Arrow Down'))
    assert composite.candidate_index == 1
    await composite.navigate_key(SimpleNamespace(key='ArrowUp'))
    assert composite.candidate_index == 0
    await composite.navigate_key(SimpleNamespace(key='ArrowLeft'))
    assert not composite.navigating_candidates and composite.active_key == group['key']
    second_row = composite.candidates.controls[1]
    await second_row.content.controls[0].on_click(None)
    assert composite.candidate_index == 1 and composite.navigating_candidates
    assert normal.items == original_stock and composite.selection == selection
    import flet as ft
    with patch.object(scope['external_url_launcher'], 'launch_url', new_callable=AsyncMock) as launch:
        await composite.navigate_key(SimpleNamespace(key='Enter'))
        launch.assert_awaited_once_with(Path(group['pdfs'][1]).as_uri(), mode=ft.LaunchMode.EXTERNAL_APPLICATION)
    await composite.show_candidates(dict(group, pdfs=group['pdfs'][:1]))
    await composite.navigate_key(SimpleNamespace(key='ArrowRight'))
    assert composite.candidate_index == 0 and not composite.navigating_candidates
    with patch.object(normal, 'open_pdf', new_callable=AsyncMock) as open_pdf:
        await composite.navigate_key(SimpleNamespace(key='Enter'))
        open_pdf.assert_awaited_once_with(group['pdfs'][0], False)
    scope['mode_dropdown'].value = 'PDFファイル名'
    scope['on_mode_change'](None)
    scope['mode_dropdown'].value = '複合'
    scope['on_mode_change'](None)
    assert not composite.preview_panel.visible and composite.active_key is None
    assert composite.heading_assy.visible
    composite.show_stock()
    assert composite.tabs.selected_index == 1 and not composite.preview_panel.visible
    assert composite.candidate_index is None and not composite.navigating_candidates
    old_selection = [i["selected"] for i in composite.items]
    await composite.invert_selection()
    assert [i["selected"] for i in composite.items] == [not x for x in old_selection]
    await composite.invert_selection()
    assert [i["selected"] for i in composite.items] == old_selection
    scope['output_folder_field'].value = str(destination)
    await composite.export()
    assert list(destination.glob('部品一覧_*.xlsx')), scope['message'].value
    with patch.object(composite.launcher, 'launch_url', new_callable=AsyncMock) as open_mock:
        await composite.open_occurrence(group['occurrences'][0])
        open_mock.assert_awaited_once()
        assert open_mock.call_args.args[0].endswith('.lnk')
    previous_message = normal.message.value
    await composite.choose_sheets()
    assert normal.message.value == previous_message
    scope['page'].pop_dialog()
    # Selection is the entire model, not the current viewport.
    composite.stock_view = False
    composite.results = [dict(group,key=str(i)) for i in range(1500)]
    await composite.select_all()
    assert len(composite.selection) == 1500 and len(composite.list.controls) == 1500
    row_ids = [id(row) for row in composite.list.controls]
    await composite.invert_selection()
    assert not composite.selection
    assert row_ids == [id(row) for row in composite.list.controls]
    await composite.invert_selection()
    assert len(composite.selection) == 1500
    # Row movement changes the preview target, never the output selection.
    composite.set_preview_visibility(False)
    composite.active_key = None
    await composite.navigate_key(SimpleNamespace(key='Arrow Down'))
    assert composite.active_key is None
    composite.scroll_offset = composite.list.controls[0].height + 1
    assert composite.first_visible_group()['key'] == '1'
    composite.scroll_offset = 0
    composite.set_preview_visibility(True)
    await composite.navigate_key(SimpleNamespace(key='Arrow Down'))
    assert composite.active_key == '0' and len(composite.selection)==1500
    await composite.navigate_key(SimpleNamespace(key='Arrow Down'))
    assert composite.active_key == '1'
    await composite.navigate_key(SimpleNamespace(key='a'))
    assert composite.active_key == '1'
    composite.view.visible = False
    await composite.navigate_key(SimpleNamespace(key='Arrow Down'))
    assert composite.active_key == '1'
    composite.view.visible = True
    composite.navigation_focused = False
    composite.key_target.focus.reset_mock()
    await scope['page'].on_keyboard_event(SimpleNamespace(key='Arrow Down'))
    composite.key_target.focus.assert_awaited_once()
    assert composite.active_key == '2'  # Arrows work after a preview button takes focus.
    composite.navigation_focused = True
    await scope['page'].on_keyboard_event(SimpleNamespace(key='Arrow Down'))
    assert composite.active_key == '3'
    with patch.object(composite, 'navigate_key', new_callable=AsyncMock) as repeated:
        holding = iter([True, True, False])
        await composite.repeat_navigation(SimpleNamespace(key='Arrow Down'),
            composite.navigation_sequence, lambda: next(holding))
        assert repeated.await_count == 2
    await composite.activate_row('1499',scroll=True)
    composite.list.scroll_to.assert_awaited()
    assert row_ids == [id(row) for row in composite.list.controls]
    composite.toggle_preview()
    assert composite.active_key is None and not composite.preview_hint.visible
    assert all(row.bgcolor is None for row in composite.list.controls)
    await composite.navigate_key(SimpleNamespace(key='Arrow Down'))
    assert composite.active_key is None
    # Late preview completion must not reappear after the pane closes.
    started, finish = threading.Event(), threading.Event()
    def delayed(path):
        started.set()
        finish.wait(5)
        return 'late-image'
    with patch.object(normal, 'make_preview', side_effect=delayed):
        pending = asyncio.create_task(composite.show_candidates(composite.results[0]))
        assert await asyncio.to_thread(started.wait, 5)
        composite.toggle_preview()
        finish.set()
        await pending
        assert not composite.preview_panel.visible and not composite.image.visible
    assert row_ids == [id(row) for row in composite.list.controls]
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
    assert scope['reference_data'].rows[1].visible
    assert scope['reference_data'].texts[1].value == '原本直接参照'
    assert '取得' in composite.sync_status.value
    await serialized_row_lifecycle(destination)
    return ['composite grouping and filters', 'part stock persistence', 'multiple PDF links',
            'preview toggle', 'PDF candidate keyboard and mouse navigation', '1500 parts select all', 'source sheet dispatch',
            'row reuse on selection and preview toggle', 'keyboard navigation preserves selection',
            'late preview discarded after close', 'distinct workbook ASSY links',
            'serialized row rebuilds remain mutable', 'closed preview clears keyboard target',
            'nanosecond workbook date display', 'research resets preview',
            'dialog restores status', 'visible top row selection', 'navigation focus routing',
            'preview closes across modes', 'Enter opens selected PDF in external app',
            'held arrow stops on release']


async def serialized_row_lifecycle(destination):
    """Wire serialization establishes Flet snapshots; a no-op transport misses this bug."""
    import flet as ft
    import msgpack
    from flet.controls.base_control import BaseControl
    from flet.controls.context import _context_page
    from flet.messaging.protocol import configure_encode_object_for_msgpack
    from frozen_selftest import MemoryConnection, Session
    from composite_mode import CompositeMode
    encode = configure_encode_object_for_msgpack(BaseControl)
    def pack(value):
        return msgpack.packb(value, default=encode)
    class WireConnection(MemoryConnection):
        def send_message(self, message):
            pack(message)
    session = Session(WireConnection())
    token = _context_page.set(session.page)
    normal = SimpleNamespace(index_database=destination/'unused.sqlite', busy=lambda:False)
    try:
        mode = CompositeMode(session.page, normal, stock_path=destination/'lifecycle-stock.json')
        mode.view.visible = True
        mode.key_target.focus = AsyncMock()
        mode.list.scroll_to = AsyncMock()
        mode.open_preview = AsyncMock()
        base = dict(identifier='PG123', material='SS400', name='ブラケット', keyword='PG123',
                    pdfs=[], pdf_status='未検出', selected=False,
                    occurrences=[dict(path=str(destination/'1001.xlsx'), sheet='ASSY'+str(i),
                                      product_id='1001', name='ブラケット', row=i) for i in range(4)])
        mode.results = [dict(base,key=str(i)) for i in range(3)]
        mode.render()
        session.page.add(mode.view)
        pack(session.get_page_patch())
        for index in range(20):
            # Expansion and stock badges rebuild rows but retain their logical keys.
            mode.items = [dict(mode.results[0])] if index % 2 else []
            mode.expand_row('0')
            session.patch_control(mode.list)
            assert all(not hasattr(c['assy'], '_frozen') for c in mode.row_cache.values())
            mode.toggle_preview()
            session.patch_control(mode.list)
            mode.toggle_preview()
            session.patch_control(mode.list)
            assert mode.active_key is None
        mode.folders = {'A', 'B'}
        mode.sheets = {'ASSY1', 'ASSY2'}
        mode.refresh_filter_labels()
        assert [c.label.value for c in mode.folder_labels.controls] == ['A', 'B']
        mode.folder_labels.controls[0].on_delete(None)
        assert mode.folders == {'B'} and mode.sheets == {'ASSY1', 'ASSY2'}
    finally:
        session.close()
        _context_page.reset(token)


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

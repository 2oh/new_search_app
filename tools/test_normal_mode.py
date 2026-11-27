"""Search, persistence, interactions, PDF output and BOM isolation regression."""
import asyncio
import inspect
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_ui_state import load


async def run(root):
    app = load('normal_test_app', root / 'main.py')
    helper = load('normal_helper', root / 'tools/frozen_selftest.py')
    import normal_search as logic
    import pdf_catalog
    assert logic.parse_search_query('Ｆ123 ss400 "MAIN BRACKET"') == ['f123', 'ss400', 'main bracket']
    assert logic.parse_search_query('err / pp ') == ['err ', ' pp ']
    assert logic.parse_search_query('err pp') == ['err', 'pp']
    assert logic.parse_search_query('"err " " pp "') == ['err ', ' pp ']
    assert logic.parse_search_query('"a/b" c') == ['a/b', 'c']
    assert logic.parse_search_query('  / "" ') == []
    ordered = [Path('b') / 'A.pdf', Path('a') / 'oldAB.pdf', Path('a') / 'newBA.pdf']
    with patch.object(logic, 'file_info', side_effect=lambda p: {
            'path': p, 'modified': 10 if 'old' in p else 20, 'available': True}):
        matches = logic.search_files(['a', 'b'], ordered)
    assert [Path(i['path']).name for i in matches] == ['newBA.pdf', 'oldAB.pdf']
    with patch.object(logic, 'file_info', side_effect=lambda p: {
            'path': p, 'modified': 999 if Path(p).parent.name == 'b' else 1, 'available': True}):
        matches = logic.search_files(['a'], ordered)
    assert [Path(i['path']).parent.name for i in matches] == ['a', 'a', 'b']
    try:
        logic.parse_search_query('"open')
        raise AssertionError('unclosed quote accepted')
    except ValueError:
        pass
    with tempfile.TemporaryDirectory(prefix='normal-mode-test-') as temp:
        previous = Path.cwd()
        os.chdir(temp)
        try:
            pdfs = Path(temp) / 'pdfs'
            pdfs.mkdir()
            (pdfs / 'nested').mkdir()
            for name, label in [('F123 SS400 MAIN BRACKET.pdf', 'first'), ('nested/F123 SS400.PDF', 'second'), ('F123 AL.pdf', 'third')]:
                with helper.fitz.open() as doc:
                    doc.new_page().insert_text((72, 72), label)
                    doc.save(pdfs / name)
            store = logic.StackStore('failure.json')
            entries = logic.add_to_stack([], [str(pdfs / 'F123 AL.pdf')]*2)
            assert len(entries) == 1
            store.save(entries)
            with patch('normal_search.os.replace', side_effect=OSError('disk failure')):
                try:
                    store.save([])
                except OSError:
                    pass
            assert store.load() == entries
            assert not list(Path('.').glob('failure.json.*.tmp'))
            session = helper.Session(helper.MemoryConnection())
            session.start_updates_scheduler()
            page = session.page
            session.get_page_patch()
            token = helper._context_page.set(page)
            scope = {}
            old_profile = sys.getprofile()
            def capture(frame, event, arg):
                if event == 'return' and frame.f_code is app.main.__code__:
                    scope.update(frame.f_locals)
            try:
                sys.setprofile(capture)
                app.main(page)
                sys.setprofile(old_profile)
                normal = scope['normal_mode']
                normal.index_database = Path(temp) / 'local-pdf.sqlite'
                normal.refresh_index_label()
                assert normal.search_controls.controls[0].controls == [normal.query]
                assert normal.search_controls.controls[1].controls == [normal.exclude]
                assert normal.tabs.length == 2
                normal.query.value = 'abc'
                normal.caret_end()
                assert normal.query.selection.base_offset == normal.query.selection.extent_offset == 3
                normal.focus = AsyncMock()
                normal.query.value = 'F123'
                await normal.search()
                assert '未取得' in scope['message'].value and not normal.results
                source_database = Path(temp) / 'update.sqlite'
                publication = Path(temp) / 'publication'
                pdf_catalog.ingest(pdfs, source_database)
                pdf_catalog.publish(source_database, publication)
                normal.publish_field.value = str(publication)
                with patch.object(normal.publish_picker, 'get_directory_path', new_callable=AsyncMock, return_value=None) as picker:
                    await normal.pick_publish()
                    picker.assert_awaited_once_with(initial_directory=str(publication))
                scope['theme_picker'].value = 'light'
                scope['change_theme'](None)
                assert json.loads(Path('config.json').read_text(encoding='utf-8'))['theme_mode'] == 'light'
                assert page.dark_theme is not None  # avoid inheriting the light color scheme
                scope['theme_picker'].value = 'dark'
                scope['change_theme'](None)
                await normal.sync_index()
                assert normal.index_database.is_file() and normal.index_root == str(pdfs)
                assert normal.root_field.read_only and not normal.root_field.can_request_focus and not normal.busy()
                assert normal.root_display.ignore_interactions and not normal.root_field.enable_interactive_selection
                before_db = normal.index_database.read_bytes()
                with patch.object(pdf_catalog, 'sync', side_effect=OSError('offline')):
                    await normal.sync_index()
                assert '前回取得したDBで検索できます' in normal.index_label.value
                assert before_db == normal.index_database.read_bytes()
                await normal.startup_sync()
                assert '取得失敗' not in normal.index_label.value
                normal.publish_field.value = ''  # no asynchronous startup work on restart tests
                scope['mode_dropdown'].value = 'PDFファイル名'
                scope['on_mode_change'](None)
                assert normal.view.visible and not scope['result_area'].visible
                assert not scope['excel_control_row'].visible
                assert scope['folder_settings_row'].controls[0] is normal.root_display
                assert scope['reference_panel'].content is scope['reference_data'].view
                assert not scope['reference_data'].rows[1].visible
                assert normal.publish_field not in normal.index_controls.controls
                assert normal.publish_field.label == '検索データ配信元フォルダ'
                assert normal.root_field.label == 'PDF検索先フォルダ'
                assert scope['output_folder_field'].label == 'PDF出力先フォルダ'
                assert normal.publish_button.content == 'フォルダを選択'
                assert scope['reference_actions'].controls[0] is scope['data_settings_button']
                assert scope['reference_actions'].controls[1].controls == [normal.sync_button, scope['exit_button']]
                assert normal.search_button.height is None and scope['composite_mode'].search_button.height is None
                assert scope['mode_row'].controls[0].controls[1].height == 48
                assert scope['settings_action_row'] not in scope['mode_row'].controls
                assert scope['excel_control_row'] not in scope['mode_row'].controls
                scope['search_folder_field'].value = str(pdfs)
                scope['output_folder_field'].value = str(Path(temp) / 'export')
                assert not normal.results
                normal.query.value = ' '
                await normal.search()
                assert normal.files is None
                normal.query.value = 'F123/SS400'
                started_search, finish_search = asyncio.Event(), asyncio.Event()
                original_worker = normal.worker
                async def held_worker(work):
                    started_search.set()
                    await finish_search.wait()
                    reports = []
                    result = work(reports.append)
                    assert reports[0] == ('ファイル名を検索中：0/3件', 0.0)
                    assert reports[-1] == ('ファイル名を検索中：3/3件', 1.0)
                    return result
                normal.worker = held_worker
                pending = asyncio.create_task(normal.search())
                await started_search.wait()
                assert normal.search_indicator.visible and scope['message'].value == 'PDF索引を検索中…'
                assert normal.search_indicator.value is None
                finish_search.set()
                await pending
                normal.worker = original_worker
                assert not normal.search_indicator.visible
                # Exercise queued progress on the real UI worker, not from the worker thread.
                release_progress = threading.Event()
                def slow_progress(report):
                    report(('照合中：1/2件', 0.5))
                    release_progress.wait(3)
                task = asyncio.create_task(original_worker(slow_progress))
                try:
                    for _ in range(20):
                        await asyncio.sleep(0.05)
                        if normal.search_indicator.value == 0.5:
                            break
                    assert normal.search_indicator.value == 0.5
                    assert scope['message'].value == '照合中：1/2件'
                finally:
                    release_progress.set()
                    await task
                def assert_progress(work):
                    reports = []
                    result = work(reports.append)
                    assert reports[0] == ('ファイル名を検索中：0/3件', 0.0)
                    assert reports[-1][1] == 1.0
                    return result
                with patch.object(normal, 'collect', side_effect=AssertionError('検索中に共有先を走査した')), patch.object(
                        normal, 'worker', new_callable=AsyncMock, side_effect=assert_progress):
                    await normal.search()
                with patch.object(normal, 'worker', new_callable=AsyncMock, side_effect=OSError('search failed')):
                    await normal.search()
                assert not normal.search_indicator.visible and not normal.busy()
                await normal.search()
                assert len(normal.results) == 2
                assert scope['message'].value == '検索結果：2件', scope['message'].value
                # New PDFs stay invisible until the daily snapshot is rebuilt and acquired.
                extra = pdfs / 'F123 SS400 EXTRA.pdf'
                extra.write_bytes((pdfs / 'F123 AL.pdf').read_bytes())
                await normal.search()
                assert len(normal.results) == 2
                pdf_catalog.ingest(pdfs, normal.index_database)
                await normal.search()
                assert len(normal.results) == 3
                extra.unlink()
                pdf_catalog.ingest(pdfs, normal.index_database)
                await normal.search()
                assert len(normal.results) == 2
                assert normal.folder_label(str(pdfs / 'nested' / 'F123 SS400.PDF')) == 'nested'
                normal.select_all()
                checked = set(normal.selection)
                normal.invert_results()
                assert not normal.selection
                normal.invert_results()
                assert normal.selection == checked
                with patch.object(normal.store, 'save', side_effect=OSError('disk full')):
                    await normal.add_selected()
                assert normal.selection == checked and not normal.items
                await normal.add_selected()
                assert len(normal.items) == 2
                assert normal.store.load() == normal.items
                for row in normal.result_table.rows:
                    addition = row.cells[-1].content.content
                    assert addition.controls[0].content.disabled
                    assert addition.controls[1].value == 'ストック済'
                    assert 'ストック済' not in row.cells[2].content.content.value
                # Selection saves serialize, preserve controls, and never disable the whole view.
                saved_rows = list(normal.stack_table.rows)
                with patch.object(normal, 'render', side_effect=AssertionError('selection rebuilt list')), \
                     patch.object(normal, 'set_busy', side_effect=AssertionError('selection disabled whole view')):
                    await asyncio.gather(normal.save_selection(False, logic.path_key(normal.items[0]['path'])),
                                         normal.save_selection(False, logic.path_key(normal.items[1]['path'])))
                    assert not any(i['selected'] for i in normal.items)
                    with patch.object(normal.store, 'save', side_effect=OSError('write denied')):
                        assert not await normal.save_selection(True)
                    assert not any(i['selected'] for i in normal.items)
                    await normal.save_selection(True)
                    await normal.invert_stock()
                    assert not any(i["selected"] for i in normal.items)
                    await asyncio.gather(normal.invert_stock(), normal.invert_stock())
                    assert not any(i["selected"] for i in normal.items)
                    await normal.invert_stock()
                assert all(a is b for a,b in zip(saved_rows, normal.stack_table.rows))
                assert normal.store.load() == normal.items and normal.pending_selection == 0
                normal.query.value = 'no-such-pdf'
                await normal.search()
                assert not normal.results and all(a is b for a,b in zip(saved_rows, normal.stack_table.rows))
                normal.query.value = 'F123'
                normal.exclude.value = 'AL'
                await normal.search()
                assert len(normal.results) == 2
                normal.exclude.value = ''
                normal.select_all()
                assert not normal.selection  # already stacked
                normal.query.value = '"MAIN BRACKET"'
                await normal.search()
                assert len(normal.results) == 1 and len(normal.items) == 2
                normal.query.value = 'pdf'
                await normal.search()
                assert not normal.results
                normal.query.value = 'F123 AL'
                await normal.search()
                normal.select_all()
                await normal.add_selected()
                assert len(normal.items) == 3
                selected = [dict(i, selected=index != 1) for index, i in enumerate(normal.items)]
                await normal.commit(selected)
                normal.completed = lambda text: None
                await normal.export()
                output = list(Path('export').glob('*.pdf'))
                assert len(output) == 1
                assert not normal.search_indicator.visible
                with helper.fitz.open(output[0]) as doc:
                    assert len(doc) == 2
                    assert 'first' in doc[0].get_text() and 'third' in doc[1].get_text()
                assert len(normal.items) == 3 and normal.store.load() == selected
                # The real shared launcher must work during the batch lock, in stock order.
                launcher = scope['external_url_launcher']
                with patch.object(launcher, 'launch_url', new_callable=AsyncMock) as launch:
                    await normal.open_selected()
                    assert launch.await_count == 2
                    assert [call.args[0] for call in launch.await_args_list] == [
                        Path(i['path']).as_uri() for i in selected if i['selected']]
                assert normal.items == selected and not scope['pdf_action_state']['processing']
                with patch.object(launcher, 'launch_url', new_callable=AsyncMock,
                                  side_effect=[OSError('unavailable'), None]) as launch:
                    await normal.open_selected()
                    assert launch.await_count == 2
                    assert '開けなかったPDF：1件' in scope['message'].value
                with patch.object(normal.store, 'save', side_effect=OSError('disk full')):
                    await normal.commit([])
                assert normal.items == selected and not scope['pdf_action_state']['processing']
                missing = dict(normal.items[0])
                missing['path'] = str(pdfs / 'missing.pdf')
                await normal.commit([missing])
                await normal.export()
                assert len(list(Path('export').glob('*.pdf'))) == 1
                assert '参照できない' in scope['message'].value
                assert not normal.search_indicator.visible
                await normal.commit(selected)
                # A slow activation read must not replace newer search metadata.
                started, release = asyncio.Event(), asyncio.Event()
                async def delayed_metadata(function):
                    started.set()
                    await release.wait()
                    return {logic.path_key(selected[0]['path']): {'available': False}}
                with patch('normal_mode.asyncio.to_thread', side_effect=delayed_metadata):
                    activation = asyncio.create_task(normal.activate_async())
                    await started.wait()
                    normal.activation_generation += 1
                    metadata_before = dict(normal.metadata)
                    release.set()
                    await activation
                assert normal.metadata == metadata_before
                scope['message'].value = 'PDF出力完了：99件'
                scope['mode_dropdown'].value = '構成部品表'
                scope['on_mode_change'](None)
                assert scope['message'].value == ''
                assert not normal.view.visible and scope['result_area'].visible
                assert scope['excel_control_row'] in scope['mode_row'].controls
                assert scope['folder_settings_row'].controls[0] is normal.root_display
                assert scope['reference_panel'].content is scope['reference_data'].view
                scope['message'].value = 'PDF出力完了：88件'
                scope['mode_dropdown'].value = 'PDFファイル名'
                scope['on_mode_change'](None)
                assert scope['message'].value == f'検索結果：{len(normal.results)}件'
                normal.load_error = 'ストック読込エラー'
                normal.activate(True)
                assert scope['message'].value == normal.load_error
                normal.load_error = ''
                assert normal.items == selected
                for width in (1200, 1920, 1699, 1700):
                    page.width = width
                    scope['on_page_resize'](None)
                    assert normal.publish_field.width == max(280, min(620, width - 240))
                    assert normal.root_display.width == max(400, min(1000, width - 720))
                    assert scope['excel_control_row'] not in scope['mode_row'].controls
                    assert not normal.preview_panel.visible
                    assert len(normal.result_table.columns) == 5
                    assert len(normal.stack_table.columns) == len(normal.result_table.columns) + 1
                    expected_path = min(600, max(450, width - 960))
                    assert normal.result_table.columns[1].fixed_width == expected_path
                    assert normal.stack_table.columns[1].fixed_width == expected_path
                    name_text = normal.stack_table.rows[0].cells[2].content.content
                    path_text = normal.stack_table.rows[0].cells[1].content.content
                    assert name_text.max_lines == 2 and not name_text.no_wrap
                    assert path_text.max_lines == 1 and path_text.no_wrap
                    assert normal.stack_table.rows[0].cells[2].content.on_hover is None
                    assert normal.result_table.columns[-1].label.controls[0].value == '追加'
                    assert normal.stack_table.columns[-1].label.controls[0].value == '選択'
                    assert len(normal.stack_table.rows) == 3
                    session.get_page_patch()
                normal.tabs.selected_index = 1
                normal.on_tab_change()
                assert normal.items == selected and not normal.image.visible
                normal.preview_target.focus = AsyncMock()
                normal.preview_list.scroll_to = AsyncMock()
                await normal.toggle_preview()
                assert normal.preview_panel.visible and normal.preview_listing.visible and not normal.tab_content.visible
                assert 'Esc 閉じる' in normal.preview_hint.value
                assert not normal.stock_actions.visible and not normal.result_actions.visible
                assert not normal.folder_button.visible
                assert normal.toolbar_actions.controls[-2:] == [normal.preview_hint, normal.preview_button]
                assert all(c.style == scope['BUTTON_STYLE_SECONDARY'] for c in normal.stock_actions.controls[:3])
                assert scope['preview_focus_overlay'].visible and scope['mode_row'].disabled
                assert normal.preview_index == 0 and normal.preview_panel.width >= 350
                assert normal.preview_heading.controls[1].width == min(normal.table_path_width() * .75, page.width * .25) * .9
                assert normal.preview_panel.width > page.width * .40
                await normal.preview_loop()
                assert normal.image.visible and Path(normal.image.src).is_file()
                normal.preview_viewport = 52
                normal.preview_focused = False
                normal.preview_target.focus.reset_mock()
                await page.on_keyboard_event(SimpleNamespace(key='Arrow Down'))
                normal.preview_target.focus.assert_awaited_once()
                assert normal.preview_index == 1 and normal.preview_rows[0].bgcolor is None
                normal.preview_list.scroll_to.assert_awaited_once_with(offset=52)
                normal.preview_focused = True
                with patch.object(normal.key_repeat, 'move', new_callable=AsyncMock) as repeated:
                    holding = iter([True, True, False])
                    await normal.key_repeat.run(SimpleNamespace(key='Arrow Down'),
                                                normal.key_repeat.sequence, lambda: next(holding))
                    assert repeated.await_count == 2
                await page.on_keyboard_event(SimpleNamespace(key='Enter'))
                assert normal.items[1]['selected'] and normal.store.load() == normal.items
                await page.on_keyboard_event(SimpleNamespace(key='Enter'))
                assert normal.items == selected
                await page.on_keyboard_event(SimpleNamespace(key='Escape'))
                assert not normal.preview_panel.visible and not normal.preview_listing.visible and normal.tab_content.visible
                assert normal.stock_actions.visible and not normal.result_actions.visible
                assert not normal.preview_target.visible and not normal.preview_focused
                assert not scope['preview_focus_overlay'].visible and not scope['mode_row'].disabled
                normal.tabs.selected_index = 0
                normal.query.value = 'F123'
                await normal.search()
                # An already stocked PDF remains ineligible for a second addition.
                await normal.toggle_preview()
                assert normal.preview_panel.visible
                assert not normal.result_actions.visible and not normal.folder_button.visible
                key = logic.path_key(normal.preview_paths[0])
                assert normal.preview_checks[key].disabled
                preview_columns = normal.preview_rows[0].content.controls
                assert 'ストック済' not in preview_columns[2].content.value
                assert preview_columns[-1].content.controls[1].value == 'ストック済'
                normal.preview_focused = True
                await page.on_keyboard_event(SimpleNamespace(key='Enter'))
                assert key not in normal.selection
                # Changing tabs and opening and closing repeatedly must keep
                # the normal and preview controls under their original parent.
                for index in range(20):
                    normal.tabs.selected_index = index % 2
                    normal.on_tab_change()
                    session.get_page_patch()
                    await normal.toggle_preview()
                    session.get_page_patch()
                    assert normal.preview_listing.visible and not normal.tab_content.visible
                    assert normal.lists.controls == [normal.tab_content, normal.preview_listing]
                    assert len(normal.preview_list.controls) == len(normal.items if index % 2 else normal.results)
                    assert normal.preview_index == 0
                    await normal.toggle_preview()
                    session.get_page_patch()
                    assert normal.tab_content.visible and not normal.preview_listing.visible
                    assert normal.folder_button.visible
                    assert normal.result_actions.visible == (index % 2 == 0)
                    assert normal.stock_actions.visible == (index % 2 == 1)
                await normal.toggle_preview()
                await normal.search()
                assert not normal.preview_panel.visible
                scope['set_pdf_action_processing'](True)
                before = list(normal.items)
                await normal.commit([])
                await normal.search()
                assert normal.items == before and normal.view.disabled and normal.search_controls.disabled
                scope['set_pdf_action_processing'](False)
                await asyncio.sleep(0.05)
                assert logic.StackStore('normal_stack.json').load() == selected
                # A fresh main() must restore both modes from the persisted config.
                for mode in ('構成部品表', '通常', 'PDFファイル名', '複合'):
                    scope['mode_dropdown'].value = mode
                    scope['on_mode_change'](None)
                    assert json.loads(Path('config.json').read_text(encoding='utf-8'))['search_mode'] == mode
                    fresh = {}
                    def capture_restart(frame, event, arg):
                        if event == 'return' and frame.f_code is app.main.__code__:
                            fresh.update(frame.f_locals)
                    restart = helper.Session(helper.MemoryConnection())
                    restart.start_updates_scheduler()
                    restart.get_page_patch()
                    restart_token = helper._context_page.set(restart.page)
                    try:
                        with patch('normal_mode.NormalMode.focus', new_callable=AsyncMock):
                            sys.setprofile(capture_restart)
                            app.main(restart.page)
                            sys.setprofile(old_profile)
                            await asyncio.sleep(0.05)
                        expected = 'PDFファイル名' if mode == '通常' else mode
                        assert fresh['mode_dropdown'].value == expected
                        assert fresh['normal_mode'].view.visible == (expected == 'PDFファイル名')
                        assert fresh['composite_mode'].view.visible == (expected == '複合')
                    finally:
                        sys.setprofile(old_profile)
                        restart.close()
                        helper._context_page.reset(restart_token)
                print('PASS: query, mixed-case PDF, no extension matching, stack dedup/persistence, selection, ordered output, errors, mode switching, resize, preview, locks')
            finally:
                sys.setprofile(old_profile)
                session.close()
                helper._context_page.reset(token)
        finally:
            os.chdir(previous)


if __name__ == '__main__':
    asyncio.run(run(Path(sys.argv[1] if len(sys.argv)>1 else '.').resolve()))

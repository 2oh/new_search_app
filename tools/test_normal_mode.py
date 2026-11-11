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
                assert normal.search_controls.controls == [normal.search_button, normal.search_indicator, normal.query]
                assert normal.tabs.length == 2
                normal.query.value = 'abc'
                normal.caret_end()
                assert normal.query.selection.base_offset == normal.query.selection.extent_offset == 3
                normal.focus = AsyncMock()
                scope['mode_dropdown'].value = '通常'
                scope['on_mode_change'](None)
                assert normal.view.visible and not scope['result_area'].visible
                assert not scope['excel_control_row'].visible
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
                assert normal.search_indicator.visible and scope['message'].value == 'PDF一覧を取得中：0件'
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
                original_collect = normal.collect
                def counted_collect(folder, report):
                    report(1000)
                    return original_collect(folder)
                def assert_progress(work):
                    reports = []
                    result = work(reports.append)
                    assert reports[0] == ('PDF一覧を取得中：1000件', None)
                    assert reports[-1][1] == 1.0
                    return result
                with patch.object(normal, 'collect', side_effect=counted_collect), patch.object(
                        normal, 'worker', new_callable=AsyncMock, side_effect=assert_progress):
                    await normal.search()
                with patch.object(normal, 'worker', new_callable=AsyncMock, side_effect=OSError('search failed')):
                    await normal.search()
                assert not normal.search_indicator.visible and not normal.busy()
                await normal.search()
                assert len(normal.results) == 2
                assert scope['message'].value == '検索結果：2件。'
                # Search itself must discover newly added files, without a refresh button.
                extra = pdfs / 'F123 SS400 EXTRA.pdf'
                extra.write_bytes((pdfs / 'F123 AL.pdf').read_bytes())
                await normal.search()
                assert len(normal.results) == 3
                extra.unlink()
                await normal.search()
                assert len(normal.results) == 2
                assert normal.folder_label(str(pdfs / 'nested' / 'F123 SS400.PDF')) == 'nested'
                normal.select_all()
                checked = set(normal.selection)
                with patch.object(normal.store, 'save', side_effect=OSError('disk full')):
                    await normal.add_selected()
                assert normal.selection == checked and not normal.items
                await normal.add_selected()
                assert len(normal.items) == 2
                assert normal.store.load() == normal.items
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
                scope['message'].value = 'PDF出力完了：88件'
                scope['mode_dropdown'].value = '通常'
                scope['on_mode_change'](None)
                assert scope['message'].value == f'検索結果：{len(normal.results)}件。'
                normal.load_error = 'ストック読込エラー'
                normal.activate(True)
                assert scope['message'].value == normal.load_error
                normal.load_error = ''
                assert normal.items == selected
                for width in (1200, 1920, 1699, 1700):
                    page.width = width
                    scope['on_page_resize'](None)
                    assert normal.preview_panel.visible == (width >= 1700)
                    assert len(normal.result_table.columns) == (6 if width < 1700 else 5)
                    assert len(normal.stack_table.columns) == len(normal.result_table.columns) + 1
                    previous_width = max(1200, width - 400) if width >= 1700 else max(600, width - 60)
                    expected_path = min(600, max(450, previous_width - 900))
                    assert normal.result_table.columns[1].fixed_width == expected_path
                    assert normal.stack_table.columns[1].fixed_width == expected_path
                    if width >= 1700:
                        assert normal.lists.width < previous_width - 150
                        assert width - normal.lists.width > 550
                    name_text = normal.stack_table.rows[0].cells[2].content.content
                    path_text = normal.stack_table.rows[0].cells[1].content.content
                    assert name_text.max_lines == 2 and not name_text.no_wrap
                    assert path_text.max_lines == 1 and path_text.no_wrap
                    assert normal.result_table.columns[-1].label.controls[0].value == '追加'
                    assert normal.stack_table.columns[-1].label.controls[0].value == '選択'
                    assert len(normal.stack_table.rows) == 3
                    session.get_page_patch()
                normal.tabs.selected_index = 1
                normal.on_tab_change()
                assert normal.items == selected and not normal.image.visible
                # Preview uses a real PDF; latest request must win.
                normal.preview_pending = (normal.preview_generation, str(pdfs / 'F123 AL.pdf'))
                await normal.preview_loop()
                assert normal.image.visible and Path(normal.image.src).is_file()
                scope['set_pdf_action_processing'](True)
                before = list(normal.items)
                await normal.commit([])
                await normal.search()
                assert normal.items == before and normal.view.disabled and normal.search_controls.disabled
                scope['set_pdf_action_processing'](False)
                await asyncio.sleep(0.05)
                assert logic.StackStore('normal_stack.json').load() == selected
                # A fresh main() must restore both modes from the persisted config.
                for mode in ('構成部品表', '通常'):
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
                        assert fresh['mode_dropdown'].value == mode
                        assert fresh['normal_mode'].view.visible == (mode == '通常')
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

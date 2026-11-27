"""Exercise extraction, resize, selection and reset with the pinned-header table."""
import asyncio
import inspect
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pandas as pd
from test_ui_state import load


async def run(root):
    app = load('layout_app', root / 'main.py')
    helper = load('layout_helper', root / 'tools/frozen_selftest.py')
    with tempfile.TemporaryDirectory(prefix='table-layout-') as temp:
        cwd = Path.cwd()
        os.chdir(temp)
        session = helper.Session(helper.MemoryConnection())
        session.start_updates_scheduler()
        page = session.page
        session.get_page_patch()
        token = helper._context_page.set(page)
        scope = {}
        profile = sys.getprofile()
        def capture(frame, event, arg):
            if event == 'return' and frame.f_code is app.main.__code__:
                scope.update(frame.f_locals)
        def current():
            return inspect.getclosurevars(scope['render_table_from_df']).nonlocals['current_df']
        try:
            sys.setprofile(capture)
            app.main(page)
            sys.setprofile(profile)
            table = scope['table']
            assert table.fixed_top_rows == 1
            assert table.data_row_height >= 72
            assert scope['table_area'].content is table
            await scope['pick_excel_result']([SimpleNamespace(path=str(root / 'tools/fixtures/app_a_excel_test.xlsx'))])
            scope['sheet_dropdown'].value = '基本確認'
            await scope['on_extract_click'](None)
            df = pd.concat([current()] * 15, ignore_index=True)
            pdfs = sorted((root / 'tools/fixtures/pdfs').rglob('*.pdf'))
            assert len(pdfs) >= 2
            eligible = list(df.index[df['出力可否'] == '可'])
            df.loc[eligible[:2], '採用PDFパス'] = [str(path) for path in pdfs[:2]]
            df.at[eligible[0], '出力対象'] = True
            df.loc[0, '品名'] = '長い部品名称' * 40 + '\n結合相手'
            scope['render_table_from_df'](df)
            selection = current()['出力対象'].copy()
            for width in (1200, 1920, 1699, 1700, 1200):
                page.width = width
                scope['on_page_resize'](None)
                assert not scope['bom_preview'].panel.visible and scope['table_area'].visible
                assert len(table.columns) == 13
                assert len(table.rows) == len(df)
                assert all(len(row.cells) == len(table.columns) for row in table.rows)
                assert current()['出力対象'].equals(selection)
                assert table.min_width >= sum(c.fixed_width or 0 for c in table.columns)
                assert all(c.fixed_width is None or c.fixed_width >= 44 for c in table.columns)
                def walk(control):
                    yield control
                    for attr in ('content', 'controls', 'cells'):
                        value = getattr(control, attr, None)
                        for child in value if isinstance(value, list) else [value]:
                            if child is not None:
                                yield from walk(child)
                second_line = [c for c in walk(table.rows[0]) if getattr(c, 'value', None) == '結合相手']
                assert len(second_line) == 1 and second_line[0].no_wrap and second_line[0].max_lines == 1
            preview = scope['bom_preview']
            assert scope['table_header'].alignment == app.ft.MainAxisAlignment.END
            assert scope['table_toolbar'].alignment == app.ft.Alignment.CENTER_RIGHT
            assert scope['table_header'].controls[-2:] == [preview.hint, preview.button]
            export_group = scope['bom_actions'][-1]
            assert export_group.controls == [scope['pdf_action_state']['export_button'], scope['result_csv_checkbox']]
            preview.key_target.focus = AsyncMock()
            preview.list.scroll_to = AsyncMock()
            closed_rows = list(table.rows)
            await preview.button.on_click(None)
            assert preview.panel.visible and not scope['table_area'].visible
            assert scope['preview_focus_overlay'].visible and not any(c.visible for c in scope['bom_actions'])
            assert [c.content.value for c in preview.heading.content.controls] == [
                '項番', '材料', '品番/PG名', '抽出対象', '出力PDF']
            assert preview.index == eligible[0] and len(preview.list.controls) == len(df)
            assert 'Esc 閉じる' in preview.hint.value and 'Enter PDFを開く' in preview.hint.value
            await preview.load()
            assert preview.image.visible and Path(preview.image.src).is_file()
            await page.on_keyboard_event(SimpleNamespace(key='ArrowDown'))
            assert preview.index == eligible[0] + 1
            await preview.list.controls[eligible[1]].on_click(None)
            assert preview.index == eligible[1]
            with patch.object(preview, 'open_pdf', new_callable=AsyncMock) as launch:
                await page.on_keyboard_event(SimpleNamespace(key='Enter'))
                launch.assert_not_awaited()
                preview.key_target.on_focus(None)
                await page.on_keyboard_event(SimpleNamespace(key='Enter'))
                launch.assert_awaited_once_with(str(pdfs[1]), False)
                index_without_pdf = next(i for i, path in enumerate(preview.paths) if not path)
                await preview.select(index_without_pdf)
                await page.on_keyboard_event(SimpleNamespace(key='NumpadEnter'))
                assert launch.await_count == 1
            await page.on_keyboard_event(SimpleNamespace(key='Escape'))
            assert not preview.panel.visible and scope['table_area'].visible
            assert not scope['preview_focus_overlay'].visible and all(c.visible for c in scope['bom_actions'])
            assert all(a is b for a, b in zip(closed_rows, table.rows))
            assert current()['出力対象'].equals(selection)
            for _ in range(5):
                await preview.button.on_click(None)
                session.get_page_patch()
                assert len(preview.list.controls) == len(df)
                await preview.button.on_click(None)
                session.get_page_patch()
                assert not preview.panel.visible
            box = scope['output_checkboxes'][0]
            box.value = False
            box.on_change(SimpleNamespace(control=box))
            assert not bool(current().at[0, '出力対象'])
            scope['reset_extract_view']()
            assert not table.rows and len(table.columns) == 1
            assert table.min_width == 240 and scope['table_area'].expand
            assert not scope['bom_preview'].panel.visible
            session.get_page_patch()
            print('PASS: BOM columns and toolbar, PDF preview row navigation and Enter, Esc, selection persistence, reset')
        finally:
            sys.setprofile(profile)
            session.close()
            helper._context_page.reset(token)
            os.chdir(cwd)


if __name__ == '__main__':
    asyncio.run(run(Path(sys.argv[1] if len(sys.argv) > 1 else '.').resolve()))

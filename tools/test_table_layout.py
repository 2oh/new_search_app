"""Exercise extraction, resize, selection and reset with the pinned-header table."""
import asyncio
import inspect
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
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
            scope['search_folder_field'].value = str(root / 'tools/fixtures/pdfs')
            await scope['on_pdf_candidate_search'](None)
            df = pd.concat([current()] * 15, ignore_index=True)
            df.loc[0, '品名'] = '長い部品名称' * 40
            scope['render_table_from_df'](df)
            selection = current()['出力対象'].copy()
            for width in (1200, 1920, 1699, 1700, 1200):
                page.width = width
                scope['on_page_resize'](None)
                wide = width >= 1700
                assert scope['hover_preview_panel'].visible == wide
                assert bool(scope['table_area'].expand) == (not wide)
                assert len(table.columns) == (13 if wide else 14)
                assert len(table.rows) == len(df)
                assert all(len(row.cells) == len(table.columns) for row in table.rows)
                assert current()['出力対象'].equals(selection)
                assert table.min_width >= sum(c.fixed_width or 0 for c in table.columns)
                assert all(c.fixed_width is None or c.fixed_width >= 44 for c in table.columns)
            box = scope['output_checkboxes'][0]
            box.value = False
            box.on_change(SimpleNamespace(control=box))
            assert not bool(current().at[0, '出力対象'])
            scope['reset_extract_view']()
            assert not table.rows and len(table.columns) == 1
            assert table.min_width == 240 and scope['table_area'].expand
            assert not scope['hover_preview_panel'].visible
            session.get_page_patch()
            print('PASS: 90 rows, long names, narrow/wide boundary resizing, selection persistence, reset, serialization')
        finally:
            sys.setprofile(profile)
            session.close()
            helper._context_page.reset(token)
            os.chdir(cwd)


if __name__ == '__main__':
    asyncio.run(run(Path(sys.argv[1] if len(sys.argv) > 1 else '.').resolve()))

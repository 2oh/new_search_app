"""Exercise bundled app and dependencies, without a Python installation or native UI."""
import asyncio
import csv
import inspect
import json
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import fitz
from flet.controls.context import _context_page
from flet.messaging.connection import Connection
from flet.messaging.session import Session
from flet.pubsub.pubsub_hub import PubSubHub


class MemoryConnection(Connection):
    def __init__(self):
        super().__init__()
        self.loop = asyncio.get_running_loop()
        self.pubsubhub = PubSubHub(self.loop)

    def send_message(self, message):
        pass


async def run_test(app, bundle, destination):
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bundle / 'selftest_data/app_a_excel_test.xlsx', destination)
    shutil.copytree(bundle / 'selftest_data/pdfs', destination / 'pdfs', dirs_exist_ok=True)
    old_cwd = Path.cwd()
    os.chdir(destination)
    session = Session(MemoryConnection())
    session.start_updates_scheduler()
    page = session.page
    session.get_page_patch()
    token = _context_page.set(page)
    scope, dialog = {}, {}

    def capture(frame, event, arg):
        if event == 'return' and frame.f_code is app.main.__code__:
            scope.update(frame.f_locals)
        if event == 'return' and scope and frame.f_code is scope['on_select_pdf_candidate'].__code__:
            dialog.update(frame.f_locals)

    old_profile = sys.getprofile()

    def visible_texts(control):
        if hasattr(control, 'value') and isinstance(control.value, str):
            yield control.value
        for attribute in ('content', 'controls', 'rows', 'cells'):
            child = getattr(control, attribute, None)
            for item in child if isinstance(child, list) else [child]:
                if item is not None and not isinstance(item, (str, int, bool)):
                    yield from visible_texts(item)
    try:
        sys.setprofile(capture)
        app.main(page)
        await scope['pick_excel_result']([SimpleNamespace(path=str(destination / 'app_a_excel_test.xlsx'))])
        scope['sheet_dropdown'].value = '基本確認'
        scope['on_sheet_change'](None)
        await scope['on_extract_click'](None)
        scope['search_folder_field'].value = str(destination / 'pdfs')
        await scope['on_pdf_candidate_search'](None)
        scope['on_select_pdf_candidate'](1)
        assert 'TEST001.pdf' in list(visible_texts(scope['table']))
        dialog['apply_candidate_selection'](str(destination / 'pdfs/nested/12345_B.pdf'))
        dialog['close_dialog'](None)
        await scope['on_pdf_candidate_search'](None)
        current = inspect.getclosurevars(scope['render_table_from_df']).nonlocals['current_df']
        assert '12345_B.pdf' in list(visible_texts(scope['table']))
        assert 'nested' in list(visible_texts(scope['table']))
        assert current['候補状態'].tolist() == ['自動採用', '手動採用'] + ['出力不可'] * 4
        preview = await asyncio.to_thread(app.create_pdf_preview_image, str(destination / 'pdfs/TEST001.pdf'))
        assert Path(preview).is_file()
        scope['output_folder_field'].value = str(destination / 'export')
        scope['result_csv_checkbox'].value = True
        await scope['on_pdf_export'](None)
        completed = next(d for d in reversed(page._dialogs.controls) if getattr(getattr(d, 'title', None), 'value', '') == 'PDF出力完了')
        completed.actions[0].on_click(None)
        assert not completed.open
        pdf = max((destination / 'export').glob('*.pdf'), key=lambda p:p.stat().st_mtime)
        assert page.title == app.APP_WINDOW_TITLE
        assert app.APP_VERSION in page.title
        assert pdf.stem.endswith('_' + app.APP_VERSION)
        with pdf.with_name(pdf.stem + '_result.csv').open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == 6 and len(rows[0]) == 21
        assert [r['出力対象'] for r in rows] == ['TRUE', 'TRUE'] + ['FALSE'] * 4
        assert [r['出力順'] for r in rows] == ['1', '2', '', '', '', '']
        original_label = app.OUTPUT_FILENAME_LABEL
        try:
            app.OUTPUT_FILENAME_LABEL = 'v1.1.1'
            version_path = Path(scope['build_output_pdf_path'](str(destination / 'export'), 'example.xlsx', 'Sheet'))
            assert version_path.stem.endswith('_v1.1.1')
            assert app.APP_WINDOW_TITLE not in version_path.name
        finally:
            app.OUTPUT_FILENAME_LABEL = original_label
        with fitz.open(pdf) as merged:
            assert len(merged) == 2
            for i, name in enumerate(['TEST001.pdf', 'nested/12345_B.pdf']):
                with fitz.open(destination / 'pdfs' / name) as source:
                    assert merged[i].get_text() == source[0].get_text()
                    assert merged[i].get_pixmap().samples == source[0].get_pixmap().samples
        (destination / 'SELFTEST_PASS.json').write_text(json.dumps({
            'frozen': bool(getattr(sys, 'frozen', False)),
            'version': app.APP_VERSION,
            'checks': ['Excel', 'search', 'manual selection', 're-search', 'output PDF filename and folder text after search', 'preview', 'PDF 2 pages', 'CSV 6 rows / 21 columns', 'title in paired output filenames', 'version-only label', 'one-click close'],
        }, indent=2), encoding='utf-8')
    finally:
        sys.setprofile(old_profile)
        session.close()
        _context_page.reset(token)
        os.chdir(old_cwd)

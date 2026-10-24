"""Real Windows shortcut creation + mocked Flet client launch, no external UI."""
import asyncio
import ctypes
from ctypes import wintypes
import inspect
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import unquote, urlparse

sys.dont_write_bytecode = True
from test_ui_state import load


def shortcut_arguments(module, path):
    ole = ctypes.OleDLL('ole32')
    module._check(ole.CoInitializeEx(None, 2))
    link, persist = ctypes.c_void_p(), ctypes.c_void_p()
    try:
        module._check(ole.CoCreateInstance(
            ctypes.byref(module.GUID('00021401-0000-0000-C000-000000000046')),
            None, 1, ctypes.byref(module.GUID('000214F9-0000-0000-C000-000000000046')),
            ctypes.byref(link)))
        module._check(module._method(link, 0, ctypes.POINTER(module.GUID), ctypes.POINTER(ctypes.c_void_p))(
            link, ctypes.byref(module.GUID('0000010B-0000-0000-C000-000000000046')), ctypes.byref(persist)))
        module._check(module._method(persist, 5, wintypes.LPCWSTR, wintypes.DWORD)(persist, str(path), 0))
        args = ctypes.create_unicode_buffer(32768)
        module._check(module._method(link, 10, wintypes.LPWSTR, ctypes.c_int)(link, args, len(args)))
        target = ctypes.create_unicode_buffer(32768)
        module._check(module._method(link, 3, wintypes.LPWSTR, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)(link, target, len(target), None, 4))
        return target.value, args.value
    finally:
        if persist:
            module._method(persist, 2)(persist)
        if link:
            module._method(link, 2)(link)
        ole.CoUninitialize()


async def run(root):
    app = load('client_launch_app', root / 'main.py')
    helper = load('client_selftest', root / 'tools/frozen_selftest.py')
    native = sys.modules['windows_file_actions']
    with tempfile.TemporaryDirectory(prefix='pdf-client-launch-') as temp:
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

        def walk(c):
            yield c
            for attr in ('content', 'controls', 'rows', 'cells'):
                v = getattr(c, attr, None)
                for child in v if isinstance(v, list) else [v]:
                    if child is not None:
                        yield from walk(child)

        try:
            sys.setprofile(capture)
            app.main(page)
            sys.setprofile(profile)
            await scope['pick_excel_result']([SimpleNamespace(path=str(root / 'tools/fixtures/app_a_excel_test.xlsx'))])
            scope['sheet_dropdown'].value = '基本確認'
            await scope['on_extract_click'](None)
            scope['search_folder_field'].value = str(root / 'tools/fixtures/pdfs')
            await scope['on_pdf_candidate_search'](None)
            current = inspect.getclosurevars(scope['render_table_from_df']).nonlocals['current_df'].copy()
            target = Path(temp) / '日本語 & 空白, フォルダ' / '図面 & 1, #50%.pdf'
            target.parent.mkdir()
            target.write_bytes(b'%PDF-test')
            current.at[0, '採用PDFパス'] = str(target)
            scope['search_folder_field'].value = str(target.parent)
            for wide in (False, True):
                fn = scope['render_table_from_df']
                dict(zip(fn.__code__.co_freevars, fn.__closure__))['use_hover_preview'].cell_contents = wide
                fn(current)
                links = [c for c in walk(scope['table'].rows[0]) if callable(getattr(c, 'on_click', None)) and c.on_click.__name__ == 'on_click']
                assert len(links) == 2 and links[0].content.value == f'({target.parent})'
                with patch.object(app.ft.UrlLauncher, 'launch_url', new_callable=AsyncMock) as launch:
                    await links[0].on_click(None)
                    shortcut = Path(unquote(urlparse(launch.call_args.args[0]).path).lstrip('/'))
                    executable, arguments = shortcut_arguments(native, shortcut)
                    assert Path(executable).name.lower() == 'explorer.exe'
                    assert arguments == f'/select,"{target}"'
                    await links[1].on_click(None)
                    assert launch.call_args.args[0] == target.as_uri()
                    assert launch.call_args.kwargs['mode'] == app.ft.LaunchMode.EXTERNAL_APPLICATION
                    scope['set_pdf_action_processing'](True)
                    await links[0].on_click(None)
                    await links[1].on_click(None)
                    assert launch.await_count == 2
                    scope['set_pdf_action_processing'](False)
            with patch.object(app.ft.UrlLauncher, 'launch_url', new_callable=AsyncMock) as launch:
                await scope['open_output_pdf'](str(target.with_name('missing.pdf')), False)
                assert '見つかりません' in scope['message'].value
                await scope['open_output_pdf'](str(target.with_suffix('.exe')), False)
                launch.assert_not_awaited()
            for select in (False, True):
                with patch.object(app.ft.UrlLauncher, 'launch_url', new_callable=AsyncMock, side_effect=RuntimeError('TEST client error')):
                    await scope['open_output_pdf'](str(target), select)
                    assert 'TEST client error' in scope['message'].value
            # Pass the complete UNC path to shortcut creation without accessing a server.
            unc = r'\\server\共有 フォルダ\図面, #50%.pdf'
            with patch.object(Path, 'is_file', return_value=True), patch.object(app, 'create_explorer_shortcut', return_value=target) as create, patch.object(app.ft.UrlLauncher, 'launch_url', new_callable=AsyncMock) as launch:
                await scope['open_output_pdf'](unc, True)
                assert create.call_args.args[0] == unc
                await scope['open_output_pdf'](unc, False)
                assert launch.call_args.args[0] == Path(unc).as_uri()
            # Processing can start during the awaited existence check.
            def file_check(_):
                scope['pdf_action_state']['processing'] = True
                return True
            with patch.object(Path, 'is_file', file_check), patch.object(app.ft.UrlLauncher, 'launch_url', new_callable=AsyncMock) as launch:
                await scope['open_output_pdf'](str(target), False)
                launch.assert_not_awaited()
            scope['pdf_action_state']['processing'] = False
            print('PASS: real COM shortcut round-trip (/select target), client URL launch, Japanese/spaces/comma/#/%/UNC, both viewport modes, busy and error paths')
            print('NOTE: foreground behavior in Explorer/Acrobat requires native UI confirmation')
        finally:
            sys.setprofile(profile)
            if scope.get('external_open_state', {}).get('directory'):
                scope['external_open_state']['directory'].cleanup()
            session.close()
            helper._context_page.reset(token)
            os.chdir(cwd)


if __name__ == '__main__':
    asyncio.run(run(Path(sys.argv[1] if len(sys.argv) > 1 else '.').resolve()))

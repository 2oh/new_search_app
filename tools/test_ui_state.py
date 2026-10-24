"""Source-level Flet session tests; these do not operate the native window.

Usage: python test_ui_state.py /path/to/repository [--baseline /path/to/main.py]
"""
import argparse
import asyncio
import importlib.util
import inspect
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import patch

# Keep test imports from changing tracked or untracked bytecode caches.
sys.dont_write_bytecode = True


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


async def verify(root, baseline):
    helper = load("selftest_helper", root / "tools/frozen_selftest.py")
    app = load("current_app", root / "main.py")
    with tempfile.TemporaryDirectory(prefix="app-a-v111-") as temporary:
        tmp = Path(temporary)
        bundle = tmp / "bundle"
        shutil.copytree(root / "tools/fixtures", bundle / "selftest_data")
        destination = tmp / "regression"
        if baseline:
            old = load("baseline_app", baseline)
            await helper.run_test(old, bundle, destination)
            old_csv = next((destination / "export").glob("*_result.csv")).read_bytes()
            old_pdf = next((destination / "export").glob("*.pdf"))
        await helper.run_test(app, bundle, destination)
        print("PASS: existing source selftest (Excel, manual candidate, re-search, PDF, CSV, preview, completion)")
        if baseline:
            new_csv = next((destination / "export").glob(f"*{app.APP_VERSION}_result.csv")).read_bytes()
            assert old_csv == new_csv, "CSV contents changed"
            new_pdf = next((destination / "export").glob(f"*{app.APP_VERSION}.pdf"))
            with helper.fitz.open(old_pdf) as left, helper.fitz.open(new_pdf) as right:
                assert len(left) == len(right)
                for a, b in zip(left, right):
                    assert a.get_text() == b.get_text()
                    assert a.get_pixmap().samples == b.get_pixmap().samples
            print("PASS: baseline/current CSV byte equality and PDF page text/render equality")

        cwd = Path.cwd()
        os.chdir(tmp)
        session = helper.Session(helper.MemoryConnection())
        session.start_updates_scheduler()
        page = session.page
        session.get_page_patch()
        token = helper._context_page.set(page)
        scope, dialog = {}, {}
        old_profile = sys.getprofile()

        def capture(frame, event, arg):
            if event == "return" and frame.f_code is app.main.__code__:
                scope.update(frame.f_locals)
            if event == "return" and scope and frame.f_code is scope["on_select_pdf_candidate"].__code__:
                dialog.update(frame.f_locals)

        def current():
            return inspect.getclosurevars(scope["render_table_from_df"]).nonlocals["current_df"]

        def texts(control):
            if isinstance(getattr(control, "value", None), str):
                yield control.value
            for attr in ("content", "controls"):
                value = getattr(control, attr, None)
                for child in value if isinstance(value, list) else [value]:
                    if child is not None:
                        yield from texts(child)

        def check(expected):
            count = len(scope["get_export_ready_df"](current()))
            assert count == expected, (count, expected)
            button = scope["pdf_action_state"]["export_button"]
            assert button.disabled == (expected == 0 or scope["pdf_action_state"]["processing"])
            assert button.opacity == (0.55 if button.disabled else 1.0)
            labels = [list(texts(c.label)) for c in scope["table"].columns]
            output_label = next(label for label in labels if "出力" in label)
            assert str(expected) in output_label, output_label

        async def read_excel(_=None):
            await scope["pick_excel_result"]([SimpleNamespace(path=str(root / "tools/fixtures/app_a_excel_test.xlsx"))])

        async def held(owner, name, callback, fail=False):
            started, release = threading.Event(), threading.Event()
            original = getattr(owner, name)
            ui_thread = threading.get_ident()

            def delayed(*args, **kwargs):
                assert threading.get_ident() != ui_thread
                started.set()
                assert release.wait(10), "worker timeout"
                if fail:
                    raise OSError("TEST failure")
                return original(*args, **kwargs)

            with patch.object(owner, name, delayed):
                task = asyncio.create_task(callback(None))
                try:
                    for _ in range(300):
                        if started.is_set() or task.done():
                            break
                        await asyncio.sleep(0.01)
                    assert started.is_set()
                    for key in ("folder_settings_row", "mode_dropdown", "excel_control_row",
                                "table_header", "table_area", "exit_button"):
                        assert scope[key].disabled, key
                    before = current().copy(deep=True)
                    await scope["close_app"](None)
                    for key in ("on_extract_click", "on_pdf_candidate_search", "on_pdf_export"):
                        await scope[key](None)
                    scope["toggle_all"](False)
                    scope["on_sheet_change"](None)
                    assert before.equals(current())
                    button = scope["pdf_action_state"]["export_button"]
                    if button:
                        assert button.disabled
                    for _ in range(3):
                        await asyncio.sleep(0.02)
                        assert not task.done()
                finally:
                    release.set()
                    await asyncio.wait_for(task, 10)
            assert not scope["pdf_action_state"]["processing"]
            for key in ("folder_settings_row", "mode_dropdown", "excel_control_row",
                        "table_header", "table_area", "exit_button"):
                assert not scope[key].disabled, key
            if fail:
                assert "TEST failure" in scope["message"].value

        try:
            sys.setprofile(capture)
            app.main(page)
            await held(app.pd, "ExcelFile", read_excel)
            await held(app.pd, "ExcelFile", read_excel, fail=True)
            await read_excel()
            scope["sheet_dropdown"].value = "基本確認"
            scope["search_folder_field"].value = str(root / "tools/fixtures/pdfs")
            scope["output_folder_field"].value = str(tmp / "ui-export")
            await held(app.pd, "read_excel", scope["on_extract_click"])
            check(0)
            await held(app, "collect_pdf_files", scope["on_pdf_candidate_search"])
            check(1)
            scope["toggle_all"](False)
            check(0)
            scope["toggle_all"](True)
            check(1)
            checkbox = next(iter(scope["output_checkboxes"].values()))
            checkbox.value = False
            checkbox.on_change(SimpleNamespace(control=checkbox))
            check(0)
            scope["toggle_all"](True)
            scope["on_select_pdf_candidate"](1)
            candidate = str(root / "tools/fixtures/pdfs/nested/12345_B.pdf")
            dialog["apply_candidate_selection"](candidate)
            check(2)
            dialog["close_dialog"](None)
            scope["on_select_pdf_candidate"](1)
            dialog["apply_candidate_selection"]("__NO_ADOPTED_PDF__")
            check(1)
            dialog["close_dialog"](None)
            scope["on_select_pdf_candidate"](1)
            scope["set_pdf_action_processing"](True)
            before = current().copy(deep=True)
            dialog["apply_candidate_selection"](candidate)
            assert before.equals(current())
            scope["set_pdf_action_processing"](False)
            dialog["apply_candidate_selection"](candidate)
            dialog["close_dialog"](None)
            check(2)
            await scope["on_pdf_candidate_search"](None)
            check(2)
            await held(app, "merge_pdfs", scope["on_pdf_export"])
            check(2)
            assert not list((tmp / "ui-export").glob("*.csv")), "CSV OFF was ignored"
            for owner, name, callback in (
                (app.pd, "read_excel", scope["on_extract_click"]),
                (app, "collect_pdf_files", scope["on_pdf_candidate_search"]),
                (app, "merge_pdfs", scope["on_pdf_export"]),
            ):
                await held(owner, name, callback, fail=True)
                check(2)
            print("PASS: processing locks, exit/candidate guards, reentry, worker scheduling and failure recovery")
            print("PASS: extraction/search, individual/all selection, manual adoption/removal, re-search, CSV OFF")

            duplicate = current().copy(deep=True)
            duplicate.at[1, "採用PDFパス"] = duplicate.at[0, "採用PDFパス"]
            duplicate = scope["update_adopted_pdf_duplicate_info"](duplicate)
            duplicate = scope["apply_duplicate_output_defaults"](duplicate)
            scope["render_table_from_df"](duplicate)
            check(1)
            scope["toggle_all"](True)
            check(2)  # Count selected rows, not distinct paths.
            scope["toggle_all"](False)
            check(0)
            # Inconsistent input must still agree with the actual export filter.
            missing = current().copy(deep=True)
            missing["採用PDFパス"] = ""
            missing["出力対象"] = True
            scope["render_table_from_df"](missing)
            check(0)
            print("PASS: duplicate selection and selected rows without adopted paths")

            # Successful no-match search after previously having a result.
            await scope["on_extract_click"](None)
            for field in scope["search_text_fields"].values():
                field.value = "NO_MATCH_FOR_THIS_TEST"
            await scope["on_pdf_candidate_search"](None)
            check(0)
            # A result reset inside a running operation must preserve its lock.
            scope["set_pdf_action_processing"](True)
            scope["reset_extract_view"]()
            assert scope["pdf_action_state"]["processing"]
            assert scope["exit_button"].disabled
            scope["set_pdf_action_processing"](False)
            await scope["on_extract_click"](None)
            with patch.object(app.pd, "read_excel", return_value=app.pd.DataFrame()):
                # Use the closure function directly: a no-header workbook may raise
                # rather than produce an empty extraction.
                worker = scope["on_extract_click"].__closure__
                cell = next(c for c in worker if c.cell_contents is scope["extract_excel_dataframe"])
                original = cell.cell_contents
                cell.cell_contents = lambda *args: app.pd.DataFrame()
                try:
                    await scope["on_extract_click"](None)
                finally:
                    cell.cell_contents = original
            assert current().empty
            assert not scope["search_text_fields"] and not scope["output_checkboxes"]
            assert scope["pdf_action_state"]["export_button"] is None
            assert scope["pdf_action_state"]["search_button"] is None
            assert not scope["table"].rows and not scope["table_header"].controls
            assert not scope["pdf_action_state"]["processing"]
            assert not scope["exit_button"].disabled
            scope["mode_dropdown"].disabled = True
            scope["set_pdf_action_processing"](True)
            scope["set_pdf_action_processing"](False)
            assert scope["mode_dropdown"].disabled, "Pre-existing disabled state lost"
            scope["mode_dropdown"].disabled = False
            print("PASS: no-match search and empty re-extraction clear old state")
        finally:
            sys.setprofile(old_profile)
            session.close()
            helper._context_page.reset(token)
            os.chdir(cwd)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("repository", type=Path)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    asyncio.run(verify(args.repository.resolve(), args.baseline.resolve() if args.baseline else None))

"""Whole-sheet Excel COM export in a dedicated Excel instance."""
from contextlib import contextmanager
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
from time import perf_counter
import uuid
from sheet_stock import sheet_key, source_path


def stamp(path):
    s = path.stat()
    return s.st_mtime_ns, s.st_size


def check_sources(items):
    actual = {}
    for item in items:
        path = source_path(item)
        if path not in actual:
            actual[path] = stamp(path)
        if actual[path] != (item['mtime'], item['size']):
            raise ValueError(f'登録時から元Excelが変更されています。データ更新後に再登録してください：{path}')


def reset_view(app, sheet):
    sheet.Activate()
    window = app.ActiveWindow
    window.Zoom = 70
    app.Goto(sheet.Range('A1'), True)
    window.ScrollRow = 1
    window.ScrollColumn = 1


def unique_name(name, used):
    base = re.sub(r'[\\/*?:\[\]]','_',name).strip("'") or 'Sheet'
    candidate = base[:31]
    n = 2
    while candidate.casefold() in used:
        suffix = f'_{n}'
        candidate = base[:31-len(suffix)] + suffix
        n += 1
    used.add(candidate.casefold())
    return candidate


def sheet_output_name(filename, sheet):
    prefix = re.split(r'\s+',Path(filename).stem.strip(),maxsplit=1)[0]
    return f'{prefix}_{sheet}' if prefix else sheet


@contextmanager
def timed_step(log, name):
    start = perf_counter()
    log.info('%s start', name)
    try:
        yield
    except Exception as exc:
        log.warning('%s failed elapsed=%.3fs error=%s', name, perf_counter() - start, type(exc).__name__)
        raise
    else:
        log.info('%s done elapsed=%.3fs', name, perf_counter() - start)


def export_sheets(items, folder, report=lambda msg: None, *, log_path=None):
    token = uuid.uuid4().hex[:10]
    log = logging.Logger('sheet-export', logging.INFO)
    handler = None
    if log_path is not None:
        try:
            handler = RotatingFileHandler(log_path, maxBytes=256 * 1024, backupCount=1, encoding='utf-8')
        except OSError:
            pass
    log.addHandler(handler or logging.NullHandler())
    if handler is not None:
        handler.setFormatter(logging.Formatter(f'%(asctime)s %(levelname)s [{token}] %(message)s'))
    try:
        with timed_step(log, 'export'):
            return _export_sheets(items, folder, report, log, token)
    finally:
        if handler is not None:
            handler.close()


def _export_sheets(items, folder, report, log, token):
    items = [item for item in items if item.get('selected',True)]
    dedup = {}
    for item in items:
        dedup.setdefault(sheet_key(item),item)
    items = list(dedup.values())
    if not items:
        raise ValueError('出力するシートを選択してください')
    log.info('selected_sheets=%d', len(items))
    report('元Excelの更新情報を確認しています…')
    with timed_step(log, 'check_sources'):
        check_sources(items)
    import pythoncom
    import win32com.client
    folder = Path(folder).resolve()
    folder.mkdir(parents=True,exist_ok=True)
    output = folder/f'構成部品表検索_{datetime.now():%Y%m%d_%H%M%S}_{token}.xlsx'
    temporary = folder/f'.export-{token}.xlsx'
    pythoncom.CoInitialize()
    app = target = None
    sources = {}
    try:
        report('Excelを起動しています…')
        with timed_step(log, 'start_excel'):
            app = win32com.client.DispatchEx('Excel.Application')
        app.Visible = False
        app.DisplayAlerts = False
        app.EnableEvents = False
        app.AutomationSecurity = 3
        target = app.Workbooks.Add()
        app.Calculation = -4135  # xlCalculationManual; retain saved values.
        app.CalculateBeforeSave = False
        # Reserve a unique temporary sheet while removing extra default sheets.
        while target.Worksheets.Count > 1:
            target.Worksheets(target.Worksheets.Count).Delete()
        placeholder = target.Worksheets(1)
        placeholder.Name = '__temporary_' + token
        used = {placeholder.Name.casefold(),'出力元一覧'.casefold()}
        mapping = []
        for i,item in enumerate(items,1):
            path = str(source_path(item))
            report(f'シート結合 {i}/{len(items)}: {item["sheet"]}')
            if path not in sources:
                sources[path] = app.Workbooks.Open(path,UpdateLinks=0,ReadOnly=True,IgnoreReadOnlyRecommended=True)
            source = sources[path]
            sheet = source.Worksheets(item['sheet'])
            # Explicit IDispatch method invocation avoids late-bound Copy being
            # evaluated as a property (which copies into a new workbook).
            sheet._oleobj_.Invoke(sheet._oleobj_.GetIDsOfNames('Copy'),0,
                                  pythoncom.DISPATCH_METHOD,0,
                                  None,target.Worksheets(target.Worksheets.Count)._oleobj_)
            copied = target.Worksheets(target.Worksheets.Count)
            copied.Visible = -1
            name = unique_name(sheet_output_name(Path(path).name,item['sheet']),used)
            copied.Name = name
            reset_view(app, copied)
            mapping.append((path,item['sheet'],name))
        converted = []
        for link_type in (1,2):
            for link in target.LinkSources(link_type) or ():
                target.BreakLink(Name=link,Type=link_type)
                converted.append(str(link))
                report(f'外部参照を現在の値に変換: {link}')
            if target.LinkSources(link_type):
                raise ValueError('値に変換できない外部参照が残りました。元Excelは変更していません')
        index = placeholder
        # The placeholder has remained first while copies were appended.
        index.Name = '出力元一覧'
        index.Range('A1:C1').Value = (('元Excel','元シート','出力シート'),)
        index.Range(index.Cells(2,1),index.Cells(len(mapping)+1,3)).NumberFormat = '@'
        index.Range(index.Cells(2,1),index.Cells(len(mapping)+1,3)).Value = tuple(mapping)
        if converted:
            first = len(mapping)+3
            index.Cells(first,1).Value = '外部参照の値変換記録（再計算・参照先更新なし）'
            index.Range(index.Cells(first+1,1),index.Cells(first+len(converted),1)).NumberFormat = '@'
            index.Range(index.Cells(first+1,1),index.Cells(first+len(converted),1)).Value = tuple((v,) for v in converted)
        index.Columns('A:C').AutoFit()
        reset_view(app, index)
        report('元Excelの更新情報を再確認しています…')
        log.info('source_workbooks=%d', len(sources))
        with timed_step(log, 'recheck_sources'):
            check_sources(items)
        report('Excelファイルを保存しています…')
        with timed_step(log, 'save_workbook'):
            target.SaveAs(str(temporary),FileFormat=51)
        with timed_step(log, 'close_output_workbook'):
            target.Close(SaveChanges=False)
        target = None
        # Windows rename refuses an existing destination.
        with timed_step(log, 'publish_output_file'):
            os.rename(temporary,output)
        report('出力完了。Excelを終了しています…')
        return output
    except Exception as exc:
        report(f'Excel出力エラー: {exc}')
        raise
    finally:
        if target is not None:
            try:
                with timed_step(log, 'close_output_after_error'):
                    target.Close(SaveChanges=False)
            except Exception:
                pass
        for number, source in enumerate(sources.values(), 1):
            try:
                with timed_step(log, f'close_source_workbook[{number}]'):
                    source.Close(SaveChanges=False)
            except Exception:
                pass
        # Release workbook/sheet proxies while Excel is still running.
        import gc
        with timed_step(log, 'release_workbook_references'):
            sources.clear()
            target = source = sheet = copied = index = placeholder = None
            gc.collect()
        if app is not None:
            try:
                with timed_step(log, 'quit_excel'):
                    app.Quit()
            except Exception:
                pass
            with timed_step(log, 'release_excel_reference'):
                app = None
        with timed_step(log, 'uninitialize_com'):
            pythoncom.CoUninitialize()
        temporary.unlink(missing_ok=True)

"""Windows integration test with a dedicated instance of Microsoft Excel."""
import hashlib
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from xml.etree import ElementTree
from zipfile import ZipFile

from openpyxl import Workbook
from openpyxl.worksheet.views import Selection

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sheet_export
from sheet_export import export_sheets, sheet_output_name, unique_name
from sheet_stock import add, load, save


NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def make_source(path):
    workbook = Workbook()
    first = workbook.active
    first.title = '架台'
    first['A1'] = '架台'
    first['C3'] = '=1+2'
    first['A20'] = '検索に一致しない行'
    first.merge_cells('F4:H4')
    first.sheet_view.zoomScale = 135
    first.sheet_view.topLeftCell = 'D15'
    first.sheet_view.selection = [Selection(activeCell='D15', sqref='D15')]
    second = workbook.create_sheet('荷台')
    second['A1'] = '荷台'
    second.freeze_panes = 'B2'
    second.sheet_view.pane.topLeftCell = 'E20'
    second.sheet_view.zoomScale = 85
    workbook.save(path)
    workbook.close()


def inspect_output(path):
    from openpyxl import load_workbook
    workbook = load_workbook(path)
    try:
        assert workbook.sheetnames == ['出力元一覧', '1001_荷台', '1001_架台'], workbook.sheetnames
        assert workbook['1001_荷台'].freeze_panes, '元シートの固定枠が解除された'
        first = workbook['1001_架台']
        assert first['A20'].value == '検索に一致しない行'
        assert first['C3'].value == '=1+2'
        assert 'F4:H4' in first.merged_cells
    finally:
        workbook.close()
    with ZipFile(path) as archive:
        for index in (1, 2, 3):
            xml = ElementTree.fromstring(archive.read(f'xl/worksheets/sheet{index}.xml'))
            view = xml.find('s:sheetViews/s:sheetView', NS)
            assert view.get('zoomScale') == '70', ElementTree.tostring(view)
            assert view.get('topLeftCell', 'A1') == 'A1', ElementTree.tostring(view)
            pane = view.find('s:pane', NS)
            if pane is not None:
                assert pane.get('topLeftCell') == 'B2', ElementTree.tostring(view)


def sha(path):
    return hashlib.sha256(path.read_bytes()).digest()


def main():
    assert sheet_output_name('1001　製品.xlsx', '架台') == '1001_架台'
    assert sheet_output_name('1001_製品.xlsx', '架台') == '1001_製品_架台'
    used = {'1001_架台'}
    assert unique_name('1001_架台', used) == '1001_架台_2'
    with TemporaryDirectory(prefix='sheet-stock-com-') as tmp:
        root = Path(tmp)
        source = root/'1001 原本.xlsx'
        make_source(source)
        timestamp = source.stat()
        before = sha(source)
        rows = [dict(root=str(root), path=source.name, sheet=sheet,
                     mtime=timestamp.st_mtime_ns, size=timestamp.st_size) for sheet in ('荷台', '架台')]
        items = add([], rows + rows)
        assert len(items) == 2
        path = root/'sheet_stock.json'
        save(path, items)
        assert load(path) == items
        messages = []
        log_path = root/'sheet_export.log'
        with patch.object(sheet_export, 'stamp', wraps=sheet_export.stamp) as stat:
            target = export_sheets(items, root, messages.append, log_path=log_path)
            assert stat.call_count == 2
        assert messages[0] == '元Excelの更新情報を確認しています…'
        assert 'Excelファイルを保存しています…' in messages
        assert messages[-1] == '出力完了。Excelを終了しています…'
        log = log_path.read_text(encoding='utf-8')
        assert f'[{target.stem.rsplit("_", 1)[-1]}]' in log
        assert str(source) not in log and source.name not in log
        steps = ('save_workbook', 'close_output_workbook', 'publish_output_file',
                 'close_source_workbook[1]', 'release_workbook_references',
                 'quit_excel', 'release_excel_reference', 'uninitialize_com', 'export')
        positions = []
        for step in steps:
            start = log.index(f'] {step} start')
            done = log.index(f'] {step} done elapsed=')
            assert start < done
            positions.append(done)
        assert positions == sorted(positions)
        inspect_output(target)
        assert sha(source) == before
        try:
            export_sheets([dict(items[0], mtime=items[0]['mtime'] - 1)], root, log_path=log_path)
        except ValueError as exc:
            assert '変更されています' in str(exc)
        else:
            raise AssertionError('更新済みの元データを拒否しなかった')
        assert 'check_sources failed elapsed=' in log_path.read_text(encoding='utf-8')
        assert list(root.glob('構成部品表検索_*.xlsx')) == [target]
        assert not list(root.glob('.export-*.xlsx'))
    print('PASS: App C names, progress, diagnostics, one stat per workbook and pass, whole sheets, order, zoom 70%, A1, freeze panes, stale rejection')


if __name__ == '__main__':
    main()

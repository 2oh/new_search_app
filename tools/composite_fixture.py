"""Isolated App C-compatible fixture; never publishes to field folders."""
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from contextlib import closing
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from composite_catalog import normalized


def create(database, root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as db, db:
        db.executescript('''
        CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE workbooks(id INTEGER PRIMARY KEY,path TEXT,folder TEXT,name TEXT,mtime INTEGER,size INTEGER);
        CREATE TABLE sheets(id INTEGER PRIMARY KEY,workbook_id INTEGER REFERENCES workbooks(id),name TEXT,position INTEGER,header INTEGER);
        CREATE TABLE parts(id INTEGER PRIMARY KEY,sheet_id INTEGER REFERENCES sheets(id),row_number INTEGER,number TEXT,pg TEXT,name TEXT,quantity TEXT,color TEXT,color_info TEXT,search_text TEXT,material TEXT);
        ''')
        db.executemany('INSERT INTO metadata VALUES(?,?)', [('version', '2'), ('extraction_version', '4'),
            ('root', str(root)), ('updated', datetime.now(timezone.utc).isoformat())])
        records = [
            ('0001_製品.xlsx', 'タイプA', '架台', [('','U123','ブラケット','SS400'), ('','↑','取付金具','A5052'), ('','↓','ブラケット','SS400'), ('','','番号なしA','')]),
            ('1002_製品.xlsx', 'タイプB', 'ASSY2', [('','U123','取付金具','SS400'), ('','U123','取付金具','SS400'), ('','U123','取付金具','SS400'), ('','H123','別番号','SS400')]),
            ('1003_製品.xlsx', 'タイプB', '架台', [('','U123','ブラケット','SS400'), ('=FORMULA','','=表示名','材料'), ('','','番号なしB','')]),
            ('番号なし.xlsx', 'タイプA', '補助', [('','P900','補助','SS400')]),
        ]
        for wid, (filename, folder, sheet, rows) in enumerate(records, 1):
            relative = str(Path(folder) / filename)
            stamp = int(datetime(2026, 11, 10 + wid, 12).timestamp() * 1e9)
            db.execute('INSERT INTO workbooks VALUES(?,?,?,?,?,?)', (wid, relative, folder, filename, stamp, 100))
            db.execute('INSERT INTO sheets VALUES(?,?,?,?,?)', (wid, wid, sheet, 0, 1))
            for rownum, (number, pg, name, material) in enumerate(rows, 2):
                text = normalized('\0'.join((str(root/relative), sheet, number, pg, name, material)))
                db.execute('INSERT INTO parts(sheet_id,row_number,number,pg,name,quantity,color,color_info,search_text,material) VALUES(?,?,?,?,?,?,?,?,?,?)',
                           (wid, rownum, number, pg, name, '1', '', '', text, material))
            from openpyxl import Workbook
            book = Workbook()
            book.active.title = sheet
            book.active.append(['品番', 'PG', '品名', '材料'])
            for row in rows:
                book.active.append(row)
            destination = root/relative
            destination.parent.mkdir(exist_ok=True)
            book.save(destination)
            book.close()

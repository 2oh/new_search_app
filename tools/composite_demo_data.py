"""Compact synthetic demo data, separate from the small regression fixture."""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from openpyxl import Workbook
from openpyxl.styles import PatternFill
import fitz
from composite_catalog import normalized


def expand_demo(database, root, pdf_root):
    root, pdf_root = Path(root), Path(pdf_root)
    names = ['ブラケット', '取付金具', '補強板', 'ベースプレート', 'カバー', 'ステー']
    materials = ['SS400 t4.5', 'SUS304 t3.0', 'A5052 t2.0']
    with closing(sqlite3.connect(database)) as db, db:
        sid = db.execute('SELECT MAX(id) FROM sheets').fetchone()[0]
        for product in range(2):
            wid = product + 5
            folder = ['タイプA', 'タイプB', 'タイプC'][product % 3]
            filename = f'{2001+product:04d}_サンプル製品{product+1:02d}.xlsx'
            relative = str(Path(folder)/filename)
            book = Workbook()
            book.remove(book.active)
            db.execute('INSERT INTO workbooks VALUES(?,?,?,?,?,?)', (wid,relative,folder,filename,0,0))
            for section, sheet in enumerate(['架台', '荷台', '鳥居', '補助']):
                sid += 1
                ws = book.create_sheet(sheet)
                ws.append(['品番','PG名','品名','材料','数量'])
                ws.freeze_panes = 'A2'
                for col, width in [('A',16),('B',16),('C',28),('D',22),('E',10)]:
                    ws.column_dimensions[col].width = width
                db.execute('INSERT INTO sheets VALUES(?,?,?,?,?)',(sid,wid,sheet,section,1))
                for offset in range(30):
                    part = (product*13+section*30+offset) % 18
                    number, pg = '', f'U{700000+part}'
                    name = names[part % len(names)] + f' {part:03d}'
                    material = materials[part % 3]
                    qty, color = '1', ''
                    if offset == 26:
                        qty = '0'
                    elif offset == 27:
                        color = 'FFFF00'
                    elif offset == 28:
                        pg = '160001'
                    elif offset == 29:
                        pg = ''
                    ws.append([number,pg,name,material,int(qty)])
                    if color:
                        ws.cell(offset+2,5).fill = PatternFill('solid',fgColor=color)
                    text = normalized('\0'.join((str(root/relative),sheet,number,pg,name,material)))
                    db.execute('INSERT INTO parts(sheet_id,row_number,number,pg,name,quantity,color,color_info,search_text,material) VALUES(?,?,?,?,?,?,?,?,?,?)',
                        (sid,offset+2,number,pg,name,qty,color,color,text,material))
            target = root/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            book.save(target)
            book.close()
            stat=target.stat()
            db.execute('UPDATE workbooks SET mtime=?,size=? WHERE id=?',(stat.st_mtime_ns,stat.st_size,wid))
        db.execute("UPDATE metadata SET value=? WHERE key='updated'",(datetime.now(timezone.utc).isoformat(),))
    for part in range(18):
        # Some missing PDFs and multiple candidates make both states testable.
        if part % 10 == 0:
            continue
        folder=pdf_root/['タイプA','タイプB','タイプC'][part%3]/f'グループ{part%6+1}'
        folder.mkdir(parents=True,exist_ok=True)
        for variant in range(2 if part%7 == 0 else 1):
            with fitz.open() as doc:
                page=doc.new_page(width=842,height=595)
                page.insert_text((50,55),f'SAMPLE DRAWING - {700000+part} - candidate {variant+1}',fontsize=22)
                page.draw_rect(fitz.Rect(160,150,620,410),color=(0,0,0),width=2)
                for x in (200,580):
                    for y in (190,370):
                        page.draw_circle((x,y),14,color=(0,0,0),width=2)
                page.insert_text((50,520),'Synthetic test data only. Not a production drawing.',fontsize=14)
                doc.save(folder/f'{700000+part}_候補{variant+1}.pdf')


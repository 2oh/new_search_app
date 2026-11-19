from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from composite_fixture import create
from composite_catalog import Catalog
from part_rules import eligible
from update_age import format_updated
import pdf_catalog


class Regressions(unittest.TestCase):
    def test_eligibility_and_inheritance_before_filter(self):
        for values in [('A', '', '', '0', ''), ('A','','','0.0',''), ('A','','','1','red'),
                       ('','','','1',''), ('','↑','','1',''), ('16A','','','1',''), ('A','↑','1601','1','')]:
            self.assertFalse(eligible(*values),values)
        self.assertTrue(eligible('','↑','P100','1',''))
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'bom.sqlite'
            create(path,Path(temp)/'books')
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("UPDATE parts SET quantity='0' WHERE sheet_id=1 AND row_number=2")
                db.execute("UPDATE parts SET color='red' WHERE sheet_id=1 AND row_number=4")
                db.execute("UPDATE parts SET pg='1601' WHERE sheet_id=2")
            groups=Catalog(path).search(ids='0001')
            self.assertEqual([(g['identifier'],g['material']) for g in groups],[('U123','A5052')])
            self.assertEqual(Catalog(path).search(ids='1002'),[])
            # All default eligible source rows still preserve their original names/links.
            self.assertTrue(groups[0]['occurrences'])

    def test_age_calendar_days(self):
        now=datetime(2026,11,19,12,tzinfo=timezone.utc).astimezone()
        local=now.replace(hour=0,minute=0)
        self.assertIn('今日',format_updated(local.isoformat(),now))
        from datetime import timedelta
        self.assertIn('昨日',format_updated((local-timedelta(days=1)).isoformat(),now))
        self.assertIn('2日前',format_updated((local-timedelta(days=2)).isoformat(),now))

    def test_pdf_excludes_and_no_match_progress(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'pdfs'; root.mkdir()
            for name in ['AB.pdf','AB old.pdf','AB obsolete.pdf']:
                (root/name).write_bytes(b'sample')
            db=Path(temp)/'pdf.sqlite'; pdf_catalog.ingest(root,db)
            _,rows=pdf_catalog.search(db,['ab'],excludes=['old','obsolete'])
            self.assertEqual([Path(r['path']).name for r in rows],['AB.pdf'])
            progress=[]
            _,rows=pdf_catalog.search(db,['missing'],lambda done,total:progress.append((done,total)))
            self.assertEqual(rows,[])
            self.assertEqual(progress[-1],(3,3))


if __name__=='__main__': unittest.main()

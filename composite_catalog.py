"""Read App C snapshots without importing or modifying the running App C."""
from collections import defaultdict
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re
import shutil
import unicodedata
import uuid

from normal_search import SearchLimitExceeded, parse_search_query
from part_rules import eligible, DEFAULT_RULES
from pdf_catalog import connect, digest, operation_lock


def normalized(value):
    return unicodedata.normalize('NFKC', str(value or '')).casefold()


def pdf_keyword(value):
    """Same transformation as A's BOM search; never use this as part identity."""
    text = str(value or '').strip()
    match = re.search(r'[A-Za-z0-9]', text)
    if not match:
        return ''
    text = text[match.start():]
    if len(text) > 1 and text[0].upper() in 'IUHF' and text[1].isdigit():
        text = text[1:]
    for pattern in ('R/L', 'L/R', 'A/B', '/'):
        text = text.split(pattern, 1)[0]
    return text.strip()


def metadata(path):
    with connect(path, True) as db:
        info = dict(db.execute('SELECT key,value FROM metadata'))
        if info.get('version') != '2':
            raise ValueError('未対応の構成部品表DBです')
        return info


def validate(path):
    info = metadata(path)
    if not Path(info.get('root', '')).is_absolute():
        raise ValueError('構成部品表DBのルートが不正です')
    datetime.fromisoformat(info['updated'])
    with connect(path, True) as db:
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('構成部品表DBの整合性エラー')
        db.execute('SELECT material,search_text FROM parts LIMIT 0')
        for row in db.execute('SELECT path FROM workbooks'):
            relative = Path(row[0])
            if relative.is_absolute() or relative.drive or '..' in relative.parts or not row[0]:
                raise ValueError(f'構成部品表DBのパスが不正です：{row[0]}')
    return info


def sync(folder, database):
    folder, database = Path(folder), Path(database)
    manifest = json.loads((folder / 'latest.json').read_text(encoding='utf-8-sig'))
    name = manifest.get('file', '')
    if not isinstance(name, str) or not re.fullmatch(r'catalog-[0-9a-f]{32}\.sqlite', name):
        raise ValueError('構成部品表DBの公開ファイル名が不正です')
    if (not isinstance(manifest.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', manifest['sha256'])
            or type(manifest.get('size')) is not int or manifest['size'] <= 0):
        raise ValueError('構成部品表DBの公開情報が不正です')
    database.parent.mkdir(parents=True, exist_ok=True)
    with operation_lock(database.with_suffix('.sync.lock')):
        if database.exists() and digest(database) == manifest['sha256']:
            validate(database)
            return False
        temporary = database.with_name(f'.bom-sync-{uuid.uuid4().hex}.sqlite')
        try:
            shutil.copyfile(folder / name, temporary)
            if temporary.stat().st_size != manifest['size'] or digest(temporary) != manifest['sha256']:
                raise ValueError('構成部品表DBの転送検証に失敗しました')
            if validate(temporary)['updated'] != manifest.get('updated'):
                raise ValueError('構成部品表DBの更新日時が一致しません')
            os.replace(temporary, database)
            return True
        finally:
            temporary.unlink(missing_ok=True)


def date_bound(value, end=False):
    if not value.strip():
        return None
    try:
        day = date.fromisoformat(value.strip())
        if end:
            day += timedelta(days=1)
        return int(datetime.combine(day, datetime.min.time()).timestamp() * 1_000_000_000)
    except (ValueError, OverflowError) as exc:
        raise ValueError('元Excel更新日は YYYY-MM-DD で入力してください') from exc


class Catalog:
    def __init__(self, database, rules=DEFAULT_RULES):
        self.info = metadata(database)
        with connect(database, True) as db:
            self.rows = [dict(row) for row in db.execute('''
                SELECT p.*,s.name AS sheet,w.path,w.folder,w.name AS filename,w.mtime,w.size
                FROM parts p JOIN sheets s ON s.id=p.sheet_id JOIN workbooks w ON w.id=s.workbook_id
                ORDER BY w.path,s.position,s.id,p.row_number,p.id''')]
        names = defaultdict(lambda: defaultdict(set))
        previous, last_pg = None, ''
        for row in self.rows:
            if row['sheet_id'] != previous:
                last_pg, previous = '', row['sheet_id']
            pg = str(row['pg'] or '').strip()
            if pg in ('↑', '↓'):
                pg = last_pg
            elif pg and pg.lower() not in ('nan', 'none'):
                last_pg = pg
            number = str(row['number'] or '').strip()
            identifier = number if pdf_keyword(number) else pg
            if identifier.lower() in ('nan', 'none'):
                identifier = ''
            material = str(row['material'] or '').strip()
            row['identifier'], row['keyword'], row['material'] = identifier, pdf_keyword(identifier), material
            # Arrow PG is the same source row's inherited identifier, so searching
            # its actual number must find this row too (before grouping).
            row['search_text'] = row['search_text'] + '\0' + normalized(pg)
            match = re.match(r'([0-9]{4})(?![0-9])', row['filename'])
            row['product_id'] = match[1] if match else ''
            identity = [identifier, material] if identifier else ['', material, row['path'], row['sheet'], row['row_number']]
            row['key'] = json.dumps(identity, ensure_ascii=False)
            row['eligible'] = eligible(number, row['pg'], pg, row['quantity'], row['color'], rules)
            name = str(row['name'] or '').strip()
            if name and row['eligible']:
                # An unidentified workbook is one source, never guessed into a product ID.
                names[row['key']][name].add(row['product_id'] or row['path'])
        self.names = {key: min(options, key=lambda name: (-len(options[name]), normalized(name), name))
                      for key, options in names.items()}
        self.folders = sorted({r['folder'] for r in self.rows})
        self.sheets = sorted({r['sheet'] for r in self.rows})

    def matching_rows(self, *, contains='', excludes='', folders=(), sheets=(), ids='', start='', end='',
                      progress=None, progress_label='明細検索・部品集約'):
        includes, excludes = parse_search_query(contains), parse_search_query(excludes)
        ids = set(filter(None, re.split(r'[\s,、]+', ids.strip())))
        if any(not re.fullmatch('[0-9]{4}', value) for value in ids):
            raise ValueError('車番は4桁の数字を空白またはカンマで区切ってください')
        begin, finish = date_bound(start), date_bound(end, True)
        if begin is not None and finish is not None and begin >= finish:
            raise ValueError('元Excel更新日の開始日が終了日より後です')
        total = len(self.rows)
        for index, row in enumerate(self.rows, 1):
            if progress and (index == 1 or index % 500 == 0 or index == total):
                progress((f'{progress_label}：{index}/{total}明細', index / total))
            if not row['eligible']:
                continue
            if folders and not any(row['folder'] == f or row['folder'].replace('\\', '/').startswith(f.replace('\\', '/').rstrip('/') + '/') for f in folders):
                continue
            if sheets and row['sheet'] not in sheets or ids and row['product_id'] not in ids:
                continue
            if begin is not None and row['mtime'] < begin or finish is not None and row['mtime'] >= finish:
                continue
            text = row['search_text']
            if not all(word in text for word in includes) or any(word in text for word in excludes):
                continue
            yield row

    def search(self, *, progress=None, max_results=None, **conditions):
        groups = {}
        seen_occurrences = set()
        for row in self.matching_rows(progress=progress, **conditions):
            key = row['key']
            if key not in groups:
                if max_results is not None and len(groups) >= max_results:
                    raise SearchLimitExceeded(max_results, '部品')
                groups[key] = dict(key=key, name=self.names.get(key, '品名未登録'), identifier=row['identifier'],
                                   material=row['material'], keyword=row['keyword'], occurrences=[], pdfs=[], pdf_status='PDF索引未取得')
            occurrence = dict(path=str(Path(self.info['root']) / row['path']), sheet=row['sheet'],
                              product_id=row['product_id'], name=str(row['name'] or ''), row=row['row_number'],
                              mtime=row['mtime'])
            identity = (key, *occurrence.values())
            if identity not in seen_occurrences:
                seen_occurrences.add(identity)
                groups[key]['occurrences'].append(occurrence)
        return sorted(groups.values(), key=lambda item: (item['identifier'], item['material'], item['key']))

    def search_sheets(self, *, progress=None, max_results=None, **conditions):
        groups = {}
        for row in self.matching_rows(progress=progress, progress_label='明細検索・シート集約', **conditions):
            key = row['sheet_id']
            if key not in groups:
                if max_results is not None and len(groups) >= max_results:
                    raise SearchLimitExceeded(max_results, 'シート')
                groups[key] = {name: row[name] for name in ('path', 'sheet', 'mtime', 'size', 'product_id')}
                groups[key].update(root=self.info['root'], hits=0)
            groups[key]['hits'] += 1
        return list(groups.values())


def attach_pdfs(groups, paths, progress=None):
    """Match A's normalized substring semantics; cache repeats across materials."""
    def norm(text):
        return re.sub(r'\s+', ' ', str(text).strip().lower())
    index = [(str(p), norm(Path(p).name)) for p in paths]
    cache = {}
    for index_number, group in enumerate(groups, 1):
        if progress and (index_number == 1 or index_number % 20 == 0 or index_number == len(groups)):
            progress((f'PDF候補の照合：{index_number}/{len(groups)}部品', index_number / len(groups)))
        key = norm(group['keyword'])
        if key not in cache:
            cache[key] = [path for path, name in index if key and key in name]
        group['pdfs'] = list(cache[key])
        group['pdf_status'] = f"{len(group['pdfs'])}件" if group['pdfs'] else '未検出'
    return groups

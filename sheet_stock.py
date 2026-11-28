"""Independent, persistent stock of full worksheets selected in composite search."""
import json
from pathlib import Path

from normal_search import path_key
from pdf_catalog import save_json


def source_path(item):
    return Path(item['root']) / item['path']


def sheet_key(item):
    return path_key(source_path(item)), item['sheet'].casefold()


def validate(items):
    if not isinstance(items, list):
        raise ValueError('シートストックの形式が不正です')
    seen = set()
    for item in items:
        if not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k]
                                             for k in ('root', 'path', 'sheet')):
            raise ValueError('シートストックの項目が不正です')
        if type(item.get('selected')) is not bool or any(type(item.get(k)) is not int for k in ('mtime', 'size')):
            raise ValueError('シートストックの選択・更新情報が不正です')
        relative = Path(item['path'])
        if not Path(item['root']).is_absolute() or relative.anchor or '..' in relative.parts:
            raise ValueError('シートストックのパスが不正です')
        key = sheet_key(item)
        if key in seen:
            raise ValueError('シートストックに重複があります')
        seen.add(key)
    return items


def load(path):
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('version') != 1:
        raise ValueError('シートストックのバージョンが不正です')
    return validate(data.get('items'))


def save(path, items):
    save_json(path, {'version': 1, 'items': validate(items)})


def same_source_version(left, right):
    return (left['mtime'], left['size']) == (right['mtime'], right['size'])


def add(items, selected_rows):
    ordered = {sheet_key(item): item for item in items}
    for row in selected_rows:
        key = sheet_key(row)
        current = ordered.get(key)
        if current is None or not same_source_version(current, row):
            ordered[key] = dict(root=row['root'], path=row['path'], sheet=row['sheet'],
                                mtime=row['mtime'], size=row['size'], selected=True)
    return list(ordered.values())

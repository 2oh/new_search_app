"""Part stock snapshots are independent of distributed databases and PDF stock."""
from copy import deepcopy
import json
from pathlib import Path

from normal_search import path_key
from pdf_catalog import save_json


def validate(items):
    if not isinstance(items, list):
        raise ValueError('部品ストックの形式が不正です')
    seen = set()
    for item in items:
        if (not isinstance(item, dict) or any(not isinstance(item.get(k), str) for k in
                ('key', 'name', 'identifier', 'material', 'keyword', 'pdf_status'))
                or type(item.get('selected')) is not bool
                or not isinstance(item.get('pdfs'), list) or not isinstance(item.get('occurrences'), list)):
            raise ValueError('部品ストックの項目が不正です')
        if item['key'] in seen:
            raise ValueError('部品ストックに重複があります')
        seen.add(item['key'])
        for path in item['pdfs']:
            if not isinstance(path, str) or not Path(path).is_absolute() or Path(path).suffix.lower() != '.pdf':
                raise ValueError('部品ストックのPDFパスが不正です')
        for occurrence in item['occurrences']:
            if (not isinstance(occurrence, dict) or any(not isinstance(occurrence.get(k), str) for k in
                    ('path', 'sheet', 'product_id', 'name')) or not Path(occurrence['path']).is_absolute()
                    or type(occurrence.get('row')) is not int):
                raise ValueError('部品ストックの使用ASSYが不正です')
    return items


def load(path):
    if not Path(path).exists():
        return []
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('version') != 1:
        raise ValueError('部品ストックのバージョンが不正です')
    return validate(data.get('items'))


def save(path, items):
    save_json(path, {'version': 1, 'items': validate(items)})


def add(items, groups):
    result = deepcopy(items)
    by_key = {item['key']: item for item in result}
    for group in groups:
        if group['key'] not in by_key:
            item = deepcopy(group)
            item['selected'] = True
            result.append(item)
            by_key[item['key']] = item
        else:
            item = by_key[group['key']]
            item['name'], item['selected'] = group['name'], True
            for occurrence in group['occurrences']:
                # Older stock entries lack mtime. Adding the same source again
                # fills in its snapshot date without creating a duplicate.
                identity = {k:v for k,v in occurrence.items() if k != 'mtime'}
                existing = next((o for o in item['occurrences']
                    if {k:v for k,v in o.items() if k != 'mtime'} == identity), None)
                if existing is None:
                    item['occurrences'].append(deepcopy(occurrence))
                elif 'mtime' in occurrence:
                    existing['mtime'] = occurrence['mtime']
            paths = {path_key(p) for p in item['pdfs']}
            for path in group['pdfs']:
                if path_key(path) not in paths:
                    item['pdfs'].append(path)
                    paths.add(path_key(path))
            item['pdf_status'] = f"{len(item['pdfs'])}件" if item['pdfs'] else group['pdf_status']
    return validate(result)

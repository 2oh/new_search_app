"""Normal-mode query parsing and durable stack, independent of Flet/Excel."""
import json
import os
from pathlib import Path
import tempfile
import unicodedata


def parse_search_query(text):
    text = unicodedata.normalize('NFKC', str(text or ''))
    quoted, slash_mode = False, False
    for char in text:
        if char == '"':
            quoted = not quoted
        elif char == '/' and not quoted:
            slash_mode = True
    words, current = [], []
    quoted = False
    for char in text:
        if char == '"':
            quoted = not quoted
        elif not quoted and (char == '/' if slash_mode else char.isspace()):
            if current:
                words.append(''.join(current).casefold())
                current = []
        else:
            current.append(char)
    if quoted:
        raise ValueError('引用符（"）を閉じてください。')
    if current:
        words.append(''.join(current).casefold())
    return [word for word in words if word.strip()]


def path_key(path):
    return os.path.normcase(os.path.abspath(os.path.normpath(path)))


def search_files(words, files, progress_callback=None):
    """Only the stem matches; neither directory names nor .pdf is searchable."""
    if not words:
        return []
    results = []
    total = len(files)
    if progress_callback:
        progress_callback(0, total)
    for number, path in enumerate(files, 1):
        path = Path(path)
        stem = unicodedata.normalize('NFKC', path.stem).casefold()
        if all(word in stem for word in words):
            results.append(file_info(str(path.absolute())))
        if progress_callback and (number % 100 == 0 or number == total):
            progress_callback(number, total)
    return sorted(results, key=lambda item: (
        path_key(str(Path(item['path']).parent)),
        -(item['modified'] if item['modified'] is not None else float('-inf')),
        Path(item['path']).name.casefold(), path_key(item['path'])))


def file_info(path):
    try:
        stat = Path(path).stat()
        available = Path(path).is_file()
        return {'path': path, 'modified': stat.st_mtime, 'available': available}
    except OSError:
        return {'path': path, 'modified': None, 'available': False}


class StackStore:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('items'), list):
            raise ValueError('スタック保存データの形式が不正です。元のファイルは保持しています。')
        items, seen = [], set()
        for item in data['items']:
            if (not isinstance(item, dict) or not isinstance(item.get('path'), str)
                    or not os.path.isabs(item['path']) or Path(item['path']).suffix.lower() != '.pdf'
                    or type(item.get('selected')) is not bool):
                raise ValueError('スタック保存データに不正な項目があります。')
            key = path_key(item['path'])
            if key not in seen:
                items.append({'path': item['path'], 'selected': item['selected']})
                seen.add(key)
        return items

    def save(self, items):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                                             prefix=self.path.name + '.', suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump({'version': 1, 'items': items}, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def add_to_stack(items, paths):
    result = [dict(item) for item in items]
    seen = {path_key(item['path']) for item in items}
    for path in paths:
        path = os.path.abspath(path)
        if path_key(path) not in seen:
            result.append({'path': path, 'selected': True})
            seen.add(path_key(path))
    return result

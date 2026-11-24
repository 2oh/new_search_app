"""PDF filename snapshots. No PDF contents or network I/O during search."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import unicodedata
import uuid
from urllib.parse import quote

from normal_search import SearchLimitExceeded, path_key

VERSION = '1'
MANIFEST = 'pdf-latest.json'


@contextmanager
def connect(path, readonly=False):
    path = Path(path).absolute()
    # Match the BOM catalog: native UNC backslashes belong in the filename,
    # not in a URI authority (file://server), which stock SQLite rejects.
    uri = 'file:' + quote(str(path), safe='/:') + '?mode=ro'
    db = sqlite3.connect(uri, uri=True) if readonly else sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


def metadata(path):
    with connect(path, True) as db:
        info = dict(db.execute('SELECT key,value FROM metadata'))
        if info.get('schema') != VERSION or info.get('kind') != 'pdf-index':
            raise ValueError('未対応のPDF索引DBです。対応するアプリで取得してください。')
        if not Path(info['root']).is_absolute():
            raise ValueError('PDF索引のルートが不正です')
        datetime.fromisoformat(info['updated'])
        return info


def validate(path):
    info = metadata(path)
    with connect(path, True) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('PDF索引DBの整合性検証に失敗しました')
        count = 0
        for row in db.execute('SELECT path,name,stem,mtime_ns,size FROM files'):
            relative = Path(row['path'])
            def invalid(reason):
                raise ValueError(
                    '\nPDF索引の検証に失敗しました。'
                    f'\n対象PDF：{Path(info["root"]) / relative}'
                    f'\n理由：{reason}'
                    f'\n相対パス（記録値）：{row["path"]!r}'
                    f'\nファイル名（記録値）：{row["name"]!r}'
                    f'\n判定された拡張子：{relative.suffix!r}'
                    f'\n検証件数：{count + 1} / {info["count"]}')
            if (relative.is_absolute() or relative.drive or '..' in relative.parts
                    or relative.name != row['name'] or relative.suffix.lower() != '.pdf'):
                invalid('相対パス・ファイル名・PDF拡張子の整合性条件を満たしません')
            if row['stem'] != unicodedata.normalize('NFKC', relative.stem).casefold():
                invalid('検索用文字列がファイル名から生成した値と一致しません')
            if type(row['mtime_ns']) is not int or type(row['size']) is not int or row['size'] < 0:
                invalid('更新日時またはファイルサイズの形式が不正です')
            count += 1
        if count <= 0 or count != int(info['count']):
            raise ValueError('PDF索引の件数が不正です')
    return info


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def digest(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


@contextmanager
def operation_lock(path):
    """Windows process lock; automatically released if the process exits."""
    import msvcrt
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError('同じPDF索引処理が既に実行中です') from exc
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def ingest(root, database, report=lambda text: None):
    """Fully enumerate filenames, fail closed on any unreadable directory/file."""
    root, database = Path(root).absolute(), Path(database).absolute()
    if not root.is_dir():
        raise FileNotFoundError(f'PDF親フォルダに接続できません：{root}')
    database.parent.mkdir(parents=True, exist_ok=True)
    temporary = database.with_name(f'.pdf-build-{uuid.uuid4().hex}.sqlite')
    def fail(error):
        raise error
    try:
        with connect(temporary) as db:
            db.executescript('''
                CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE files(path TEXT PRIMARY KEY,name TEXT NOT NULL,
                    stem TEXT NOT NULL,mtime_ns INTEGER NOT NULL,size INTEGER NOT NULL);
            ''')
            count, skipped = 0, 0
            for folder, directories, names in os.walk(root, onerror=fail, followlinks=False):
                # The existing collector does not traverse directory symlinks either.
                report(f'フォルダを確認中：{folder}')
                for name in names:
                    if not name.lower().endswith('.pdf'):
                        continue
                    path = Path(folder) / name
                    if name.lower() == '.pdf':
                        skipped += 1
                        report(f'除外PDF：{path} / 理由：ファイル名が.pdfのみ')
                        continue
                    stat = path.stat()  # disappearance/access failure aborts this generation
                    db.execute('INSERT INTO files VALUES (?,?,?,?,?)', (
                        str(path.relative_to(root)), name,
                        unicodedata.normalize('NFKC', path.stem).casefold(),
                        stat.st_mtime_ns, stat.st_size))
                    count += 1
                    if count % 1000 == 0:
                        report(f'PDF登録：{count}件')
            report(f'PDF走査完了：登録対象 {count}件 / .pdfのみの除外 {skipped}件')
            if not count:
                raise ValueError('PDFが0件のため更新・公開を中止しました。対象フォルダを確認してください。')
            info = {'kind': 'pdf-index', 'schema': VERSION, 'root': str(root),
                    'updated': datetime.now(timezone.utc).isoformat(), 'count': str(count),
                    'skipped_extension_only': str(skipped)}
            db.executemany('INSERT INTO metadata VALUES (?,?)', info.items())
            db.commit()
        validate(temporary)
        os.replace(temporary, database)
        report(f'索引作成完了：{count}件 / 除外：{skipped}件')
        return info
    finally:
        temporary.unlink(missing_ok=True)


def publish(database, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    name = f'pdf-catalog-{uuid.uuid4().hex}.sqlite'
    target = folder / name
    try:
        with connect(database, True) as source, connect(target) as dest:
            source.backup(dest)
        info = validate(target)
        manifest = {'file': name, 'sha256': digest(target), 'size': target.stat().st_size,
                    'updated': info['updated']}
        save_json(folder / MANIFEST, manifest)
        return manifest
    except Exception:
        target.unlink(missing_ok=True)
        raise


def sync(folder, local_database):
    folder, local_database = Path(folder), Path(local_database)
    manifest = json.loads((folder / MANIFEST).read_text(encoding='utf-8-sig'))
    name = manifest.get('file', '')
    if not isinstance(name, str) or not re.fullmatch(r'pdf-catalog-[0-9a-f]{32}\.sqlite', name):
        raise ValueError('PDF索引の公開ファイル名が不正です')
    if (not isinstance(manifest.get('sha256'), str)
            or not re.fullmatch('[0-9a-f]{64}', manifest['sha256'])
            or type(manifest.get('size')) is not int or manifest['size'] <= 0):
        raise ValueError('PDF索引の公開情報が不正です')
    local_database.parent.mkdir(parents=True, exist_ok=True)
    with operation_lock(local_database.with_suffix('.sync.lock')):
        if local_database.exists() and digest(local_database) == manifest['sha256']:
            validate(local_database)
            return False
        temporary = local_database.with_name(f'.pdf-sync-{uuid.uuid4().hex}.sqlite')
        try:
            shutil.copyfile(folder / name, temporary)
            if temporary.stat().st_size != manifest['size'] or digest(temporary) != manifest['sha256']:
                raise ValueError('PDF索引の転送検証に失敗しました。前回のDBを保持します。')
            info = validate(temporary)
            if info['updated'] != manifest.get('updated'):
                raise ValueError('PDF索引の更新日時が公開情報と一致しません')
            os.replace(temporary, local_database)
            return True
        finally:
            temporary.unlink(missing_ok=True)


def snapshot_paths(database):
    """Read one generation without touching the source PDFs; keep ingest order."""
    if not Path(database).is_file():
        raise FileNotFoundError('PDF索引DBが未取得です。公開先を設定し、最新データ取得を実行してください。')
    with connect(database, True) as db:
        info = dict(db.execute('SELECT key,value FROM metadata'))
        if info.get('schema') != VERSION or info.get('kind') != 'pdf-index':
            raise ValueError('未対応のPDF索引DBです')
        root = Path(info['root'])
        paths = [root / row[0] for row in db.execute('SELECT path FROM files ORDER BY rowid')]
    return info, paths


def search(database, words, progress_callback=None, excludes=(), *, max_results=None):
    """Search exclusively local data; return the same result shape/order as A."""
    if not Path(database).is_file():
        raise FileNotFoundError('PDF索引DBが未取得です。公開先を設定し、最新データ取得を実行してください。')
    # Keep metadata and rows on one connection so a generation cannot change between reads.
    with connect(database, True) as db:
        info = dict(db.execute('SELECT key,value FROM metadata'))
        if info.get('schema') != VERSION or info.get('kind') != 'pdf-index':
            raise ValueError('未対応のPDF索引DBです')
        total = int(info['count'])
        root = Path(info['root'])
        results = []
        if progress_callback:
            progress_callback(0, total)
        for number, row in enumerate(db.execute('SELECT * FROM files'), 1):
            if words and all(word in row['stem'] for word in words) and not any(word in row['stem'] for word in excludes):
                if max_results is not None and len(results) >= max_results:
                    raise SearchLimitExceeded(max_results, '件')
                results.append({'path': str(root / row['path']),
                                'modified': row['mtime_ns'] / 1_000_000_000,
                                'available': True})  # Availability is checked when actually used.
            if progress_callback and (number % 100 == 0 or number == total):
                progress_callback(number, total)
    results.sort(key=lambda item: (path_key(str(Path(item['path']).parent)),
                 -item['modified'], Path(item['path']).name.casefold(), path_key(item['path'])))
    return info, results

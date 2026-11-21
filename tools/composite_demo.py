"""Launch an isolated sample: no real config, stock, published DB or local DB changes."""
import argparse
import os
from pathlib import Path
import sys
import tempfile
import uuid
import json
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.composite_fixture import create
from tools.composite_demo_data import expand_demo
import composite_catalog
import pdf_catalog


def prepare(destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    publication = destination/'配信元'
    publication.mkdir()
    source = destination/'bom.sqlite'
    create(source, destination/'構成部品表')
    pdfs = destination/'PDF'
    pdfs.mkdir()
    expand_demo(source, destination/'構成部品表', pdfs)
    name = 'catalog-' + uuid.uuid4().hex + '.sqlite'
    data = publication/name
    data.write_bytes(source.read_bytes())
    pdf_catalog.save_json(publication/'latest.json', dict(file=name, sha256=pdf_catalog.digest(data),
        size=data.stat().st_size, updated=composite_catalog.metadata(data)['updated']))
    import fitz
    for name in ('123 first.pdf', '123 second.pdf', 'P900.pdf'):
        with fitz.open() as document:
            document.new_page().insert_text((72,72), name)
            document.save(pdfs/name)
    pdf_catalog.ingest(pdfs, destination/'pdf.sqlite')
    pdf_catalog.publish(destination/'pdf.sqlite', publication)
    output = destination/'出力'
    output.mkdir()
    pdf_catalog.save_json(destination/'config.json', dict(search_mode='複合',pdf_index_publish=str(publication),output_folder=str(output)))
    return destination


def select_demo(storage, new=False):
    """Reuse the current compact sample; a new sample never deletes the old one."""
    storage = Path(storage).resolve()
    storage.mkdir(parents=True, exist_ok=True)
    pointer = storage/'composite-demo-current.json'
    destination = None
    if not new and pointer.exists():
        name = json.loads(pointer.read_text(encoding='utf-8'))['directory']
        candidate = storage/name
        if candidate.parent != storage or not name.startswith('composite-demo-'):
            raise ValueError('サンプルの参照先が不正です')
        if not (candidate/'config.json').is_file():
            raise FileNotFoundError('前回のサンプルが見つかりません。--new-sample で新規作成できます。')
        return candidate
    if not new:
        # Migrate the most recent compact sample, including its existing stock.
        for candidate in sorted(storage.glob('composite-demo-*'), key=lambda p:p.stat().st_mtime_ns, reverse=True):
            if not candidate.is_dir() or not (candidate/'config.json').is_file():
                continue
            try:
                with pdf_catalog.connect(candidate/'bom.sqlite', True) as db:
                    count = db.execute('SELECT COUNT(*) FROM parts').fetchone()[0]
                if count <= 300:
                    destination = candidate
                    break
            except Exception:
                continue
    if destination is None:
        destination = prepare(storage/('composite-demo-'+uuid.uuid4().hex[:8]))
    pdf_catalog.save_json(pointer, {'directory':destination.name})
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--new-sample', action='store_true', help='前回のサンプルを残して新規作成')
    args = parser.parse_args()
    destination = select_demo(Path(__file__).resolve().parents[1]/'storage', new=args.new_sample)
    print(f'サンプル保存先：{destination}', flush=True)
    if args.prepare_only:
        pdf_catalog.sync(destination/'配信元', destination/'local'/'DrawingPdfSearch'/'pdf_catalog.sqlite')
        composite_catalog.sync(destination/'配信元', destination/'local'/'DrawingPdfSearch'/'bom_catalog.sqlite')
        raise SystemExit(0)
    os.environ['LOCALAPPDATA'] = str(destination/'local')
    os.chdir(destination)
    import flet as ft
    import main as application
    ft.run(application.main, assets_dir=str(Path(__file__).resolve().parents[1]/'assets'))

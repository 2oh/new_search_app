"""Launch an isolated sample: no real config, stock, published DB or local DB changes."""
import os
from pathlib import Path
import sys
import tempfile
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from composite_fixture import create
import composite_catalog
import pdf_catalog


def prepare(destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    publication = destination/'配信元'
    publication.mkdir()
    source = destination/'bom.sqlite'
    create(source, destination/'構成部品表')
    name = 'catalog-' + uuid.uuid4().hex + '.sqlite'
    data = publication/name
    data.write_bytes(source.read_bytes())
    pdf_catalog.save_json(publication/'latest.json', dict(file=name, sha256=pdf_catalog.digest(data),
        size=data.stat().st_size, updated=composite_catalog.metadata(data)['updated']))
    pdfs = destination/'PDF'
    pdfs.mkdir()
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


if __name__ == '__main__':
    destination = prepare(Path(__file__).resolve().parents[1]/'storage'/('composite-demo-' + uuid.uuid4().hex[:8]))
    print(f'サンプル保存先：{destination}', flush=True)
    os.environ['LOCALAPPDATA'] = str(destination/'local')
    os.chdir(destination)
    import flet as ft
    import main as application
    ft.run(application.main, assets_dir=str(Path(__file__).resolve().parents[1]/'assets'))

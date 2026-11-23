"""Nonblocking publication checks; checking never replaces a local snapshot."""
import asyncio
from datetime import datetime
import json
from pathlib import Path
import re
import flet as ft
import pdf_catalog
import composite_catalog
from update_age import format_updated


class PublicationCheck:
    def __init__(self):
        self.cache = {}

    def inspect(self, folder, database, kind):
        database = Path(database)
        result = dict(state='unknown', updated='', root='', count=None, error='')
        try:
            stat = database.stat()
            signature = (str(database.resolve()), stat.st_mtime_ns, stat.st_size, kind)
            cached = self.cache.get(kind)
            local = cached[1] if cached and cached[0] == signature else None
            if local is None:
                info = (pdf_catalog.validate if kind == 'pdf' else composite_catalog.validate)(database)
                with pdf_catalog.connect(database, True) as db:
                    count = db.execute('SELECT COUNT(*) FROM ' + ('files' if kind == 'pdf' else 'workbooks')).fetchone()[0]
                local = dict(updated=info['updated'], root=info['root'], count=count,
                    digest=pdf_catalog.digest(database), size=stat.st_size)
                after = database.stat()
                if (after.st_mtime_ns, after.st_size) != (stat.st_mtime_ns, stat.st_size):
                    raise OSError('ローカルデータ更新中です。再確認してください')
                self.cache[kind] = (signature, local)
            result.update(updated=local['updated'], root=local['root'], count=local['count'])
        except Exception as exc:
            local = None
            result['error'] = str(exc)
        try:
            if not folder:
                raise ValueError('設定から配信元フォルダを指定してください')
            name = 'pdf-latest.json' if kind == 'pdf' else 'latest.json'
            manifest = json.loads((Path(folder)/name).read_text(encoding='utf-8-sig'))
            prefix = 'pdf-catalog' if kind == 'pdf' else 'catalog'
            if (not re.fullmatch(prefix+r'-[0-9a-f]{32}\.sqlite', str(manifest.get('file','')))
                    or not re.fullmatch('[0-9a-f]{64}', str(manifest.get('sha256','')))
                    or type(manifest.get('size')) is not int or manifest['size'] <= 0):
                raise ValueError('配信情報の形式が不正です')
            datetime.fromisoformat(manifest['updated'])
            result['state'] = 'current' if (local and local['digest'] == manifest['sha256']
                and local['size'] == manifest['size'] and local['updated'] == manifest['updated']) else 'pending'
            result['error'] = ''
        except Exception as exc:
            result['error'] = str(exc)
        return result


class ReferenceData:
    def __init__(self, page, normal, composite, warning_style):
        self.page, self.normal, self.composite = page, normal, composite
        self.warning_style = warning_style
        self.default_style = normal.sync_button.style
        self.checker = PublicationCheck()
        self.generation = 0
        self.running = False
        self.rerun = False
        self.mode = '複合'
        self.states = [dict(state='unknown',updated='',root='',count=None,error='未確認') for _ in range(2)]
        self.texts = [ft.Text(size=12), ft.Text(size=12)]
        self.reference_labels = [ft.Container(text, on_hover=self.highlight_reference) for text in self.texts]
        self.status = [ft.Text(size=12), ft.Text(size=12)]
        self.rows = [ft.Row([ft.Text(label, width=86, size=12),
            ft.Column([self.reference_labels[i], self.status[i]], spacing=0, expand=True)],
            vertical_alignment=ft.CrossAxisAlignment.START, spacing=2)
            for i,label in enumerate(['図面ＰＤＦ：','構成部品表：'])]
        self.view = ft.Column([ft.Text('参照データ',size=12,weight=ft.FontWeight.BOLD), *self.rows],spacing=3)
        self.render()

    def set_mode(self, mode):
        self.mode = mode
        for text in self.texts:
            text.color = None
        self.render()

    def highlight_reference(self, event):
        label = event.control.content
        hovered = event.data is True or event.data == 'true'
        label.color = ft.Colors.PRIMARY if hovered and label.tooltip else None
        self.page.update()

    def render(self):
        captions = dict(current='最新の配信データを取込済', pending='未取込配信データがあります', unknown='配信状況を確認できません')
        for i,state in enumerate(self.states):
            self.texts[i].value = ('索引DB参照　'+format_updated(state['updated'])+' 時点') if state['updated'] else '索引DB参照　未取得'
            self.texts[i].tooltip = f"索引DB作成元：{state['root'] or '未取得'}"
            count = '' if state['count'] is None else f'（全{state["count"]:,}件）'
            self.status[i].value = captions[state['state']] + count
            self.status[i].color = ft.Colors.ERROR if state['state']=='unknown' else (ft.Colors.TERTIARY if state['state']=='pending' else None)
            self.status[i].tooltip = state['error'] or ('件数はPDFファイル数です。' if i == 0 else '件数は構成部品表Excelファイル数です。') + '最後の確認時点の配信状況です。起動中は約5分ごとに確認します。'
        self.rows[1].visible = self.mode != 'PDFファイル名'
        if self.mode == '構成部品表':
            self.texts[1].value = '原本直接参照'
            self.texts[1].tooltip = None
            self.status[1].value = '選択したExcelを直接読み込む'
            self.status[1].color = None
            self.status[1].tooltip = 'Excel保存後に「抽出実行」を押すと反映します。'
        # The button always updates both snapshots, regardless of the visible mode.
        current = all(s['state']=='current' for s in self.states)
        pending = any(s['state']=='pending' for s in self.states)
        self.normal.sync_button.disabled = bool(self.normal.busy()) or current
        self.normal.sync_button.style = self.warning_style if pending else self.default_style
        self.normal.sync_button.tooltip = '両方の配信データを取込済です' if current else '図面PDF・構成部品表の配信データを取得します'

    def invalidate(self):
        self.generation += 1
        for state in self.states:
            state['state'], state['error'] = 'unknown', '配信元の変更後、まだ確認していません'
        self.render()

    async def refresh(self):
        if self.running:
            self.rerun = True
            return
        self.running = True
        generation = self.generation
        folder = self.normal.publish_field.value or ''
        try:
            results = await asyncio.gather(*[
                asyncio.to_thread(self.checker.inspect, folder, database, kind)
                for database,kind in [(self.normal.index_database,'pdf'),(self.composite.database,'bom')]])
            if generation == self.generation and folder == (self.normal.publish_field.value or ''):
                self.states = results
                self.render()
                self.page.update()
        finally:
            self.running = False
            if self.rerun:
                self.rerun = False
                self.page.run_task(self.refresh)

    async def periodic(self):
        while True:
            await asyncio.sleep(300)
            if not self.normal.busy():
                await self.refresh()

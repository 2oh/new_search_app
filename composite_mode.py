"""Composite search: row filters, part grouping, optional PDF preview and stock."""
import asyncio
import tempfile
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import flet as ft
import composite_catalog as catalog
import composite_stock as stock
from composite_desktop import create_sheet_shortcut
from composite_export import export_parts
from normal_search import add_to_stack
import pdf_catalog
from part_rules import DEFAULT_RULES
from update_age import format_updated
from composite_rows import CompositeRows

SHOW_PDF_PREVIEW = 'PDFプレビューを表示'
HIDE_PDF_PREVIEW = 'PDFプレビューを閉じる'


class CompositeMode(CompositeRows):
    def __init__(self, page, normal, *, database=None, stock_path='part_stock.json', rules=DEFAULT_RULES):
        self.page, self.normal = page, normal
        self.rules = rules
        self.launcher = ft.UrlLauncher()
        self.launch_directory = tempfile.TemporaryDirectory(prefix='part-sheet-launch-')
        self.database = Path(database) if database else normal.index_database.with_name('bom_catalog.sqlite')
        self.stock_path = Path(stock_path)
        self.results, self.selection, self.items = [], set(), []
        self.catalog = None
        self.load_error = ''
        try:
            self.items = stock.load(self.stock_path)
        except Exception as exc:
            self.load_error = f'部品ストックを読み込めません。元データを保護するため変更を停止します：{exc}'
        self.folders, self.sheets = set(), set()
        self.stock_view = False
        self.preview_generation = 0
        self.preview_group = None
        self.preview_lock = asyncio.Lock()
        self.pdf_selection = set()
        self.index_label = ft.Text(size=12, max_lines=3, overflow=ft.TextOverflow.ELLIPSIS)
        self.sync_status = ft.Text(size=12, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)
        self.refresh_index_label()
        self.query = ft.TextField(label='含む文字列', hint_text='空白区切りでAND検索（例："ab c"）', expand=True, on_submit=self.search)
        self.exclude = ft.TextField(label='除く文字列', hint_text='いずれかを含む明細を除外', expand=True, on_submit=self.search)
        self.progress = ft.ProgressBar(value=None, visible=False, width=140)
        self.search_button = ft.Button('検索', on_click=self.search)
        self.folder_button = ft.OutlinedButton('対象種別：すべて', on_click=self.choose_folders)
        self.sheet_button = ft.OutlinedButton('対象ASSY：すべて', on_click=self.choose_sheets)
        self.folder_labels = ft.Row(wrap=True, spacing=4, run_spacing=4, expand=True)
        self.sheet_labels = ft.Row(wrap=True, spacing=4, run_spacing=4, expand=True)
        self.folder_button.width = self.sheet_button.width = 170
        self.ids = ft.TextField(label='車番', hint_text='9999', width=170, on_submit=self.search)
        self.start = ft.TextField(label='Excel更新日・開始', hint_text='YYYY-MM-DD', width=175)
        self.end = ft.TextField(label='Excel更新日・終了', hint_text='YYYY-MM-DD', width=175)
        self.filters = ft.Container(ft.Column([
            ft.Row([self.folder_button, self.folder_labels], spacing=8),
            ft.Row([self.sheet_button, self.sheet_labels], spacing=8),
            ft.Row([self.ids, self.start, self.end], wrap=True),
        ], spacing=6), padding=ft.Padding.only(left=210))
        # Filters stay below the entire search/reference row.
        self.search_controls = ft.Column([ft.Row([self.query]), ft.Row([self.exclude])], spacing=6, expand=True)
        self.count = ft.Text()
        self.preview_button = ft.OutlinedButton(SHOW_PDF_PREVIEW, on_click=self.toggle_preview)
        self.preview_hint = ft.Text('カーソルで上下移動', size=12, visible=False)
        self.result_tab = ft.Tab(label='検索結果')
        self.stock_tab = ft.Tab(label='部品ストック')
        self.add_button = ft.Button('部品ストックへ追加', on_click=self.add_selected)
        self.remove_button = ft.TextButton('選択部品を削除', on_click=self.remove_selected, visible=False)
        self.export_button = ft.Button('部品一覧Excel出力', on_click=self.export, visible=False)
        self.toolbar = ft.Row([self.count,
                              ft.TextButton('全選択', on_click=self.select_all), ft.TextButton('全解除', on_click=self.select_none), ft.TextButton('選択を反転', on_click=self.invert_selection),
                              self.add_button, self.remove_button, self.export_button,
                              ft.Row([self.preview_button, self.preview_hint], tight=True, spacing=8)], wrap=True)
        self.list = ft.ListView(expand=True, spacing=0, build_controls_on_demand=True)
        self.image = ft.Image(src='', fit=ft.BoxFit.CONTAIN, width=400, expand=True, visible=False)
        self.preview_label = ft.Text('↑↓でプレビューする部品を移動できます', selectable=True)
        self.candidates = ft.ListView(height=160, spacing=0)
        self.preview_panel = ft.Container(ft.Column([
            self.preview_label, self.candidates, ft.Button('選択PDFをPDFストックへ追加', on_click=self.add_pdfs), self.image,
        ], expand=True), width=420, padding=8, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST, visible=False)
        self.init_rows()
        self.render()

    def message(self, text):
        self.normal.message.value = text
        self.page.update()

    def refresh_index_label(self):
        try:
            info = catalog.metadata(self.database)
            updated = format_updated(info['updated'])
            self.index_label.value = f'構成部品表：{updated}'
        except Exception:
            self.index_label.value = '構成部品表DBは未取得です'
        self.index_label.tooltip = self.index_label.value

    async def sync_index(self, folder):
        try:
            changed = await asyncio.to_thread(catalog.sync, folder, self.database)
            self.refresh_index_label()
            if changed:
                self.catalog = None
                self.results, self.selection = [], set()
                self.clear_preview()
            status = '構成部品表の最新データを取得しました' if changed else '配信済みの最新版と一致'
        except Exception as exc:
            self.refresh_index_label()
            status = f'構成部品表の取得失敗（既存DBは保持）：{exc}'
            self.index_label.value += ' / 取得失敗'
            self.index_label.tooltip = status
        self.sync_status.value = status
        self.sync_status.tooltip = status
        self.render()
        return status

    def pdf_updated(self):
        self.results, self.selection = [], set()
        self.clear_preview()
        self.render()

    def activate(self, active):
        self.view.visible = active
        self.preview_generation += 1
        if active:
            self.refresh_index_label()
            self.normal.refresh_index_label()
            self.normal.message.value = self.load_error or '構成部品表の明細を検索し、品番／PG＋材料でまとめます'

    async def ensure_catalog(self):
        if self.catalog is None:
            self.catalog = await asyncio.to_thread(catalog.Catalog, self.database, self.rules)
        return self.catalog

    async def choose_folders(self, event=None):
        await self.choose('folders', '対象種別', self.folder_button)

    async def choose_sheets(self, event=None):
        await self.choose('sheets', '対象ASSY', self.sheet_button)

    def refresh_filter_labels(self):
        for attribute, title, button, labels in [
                ('folders', '対象種別', self.folder_button, self.folder_labels),
                ('sheets', '対象ASSY', self.sheet_button, self.sheet_labels)]:
            values = getattr(self, attribute)
            button.content = f'{title}：{len(values)}件' if values else f'{title}：すべて'
            def remove(event, attribute=attribute, value=None):
                if self.normal.busy():
                    return
                getattr(self, attribute).discard(value)
                self.refresh_filter_labels()
                self.page.update()
            labels.controls = [ft.Chip(label=ft.Text(value or '（直下）', size=13),
                on_delete=lambda e, value=value, remove=remove: remove(e, value=value))
                for value in sorted(values)]
            labels.visible = bool(values)

    async def choose(self, attribute, title, button):
        if self.normal.busy():
            return
        previous_message = self.normal.message.value
        failed = False
        self.normal.set_busy(True, '選択肢を読み込んでいます…')
        self.page.update()
        try:
            model = await self.ensure_catalog()
            options = sorted(set(getattr(model, attribute)) | getattr(self, attribute))
        except Exception as exc:
            failed = True
            self.message(f'構成部品表DBを読み込めません：{exc}')
            return
        finally:
            self.normal.set_busy(False)
            if not failed:
                self.normal.message.value = previous_message
            self.page.update()
        checked = set(getattr(self, attribute))
        listing = ft.ListView(height=360, width=520, build_controls_on_demand=True)
        def redraw(event=None):
            def change(e, value):
                if e.control.value:
                    checked.add(value)
                else:
                    checked.discard(value)
            listing.controls = [ft.Checkbox(label=value or '（直下）', value=value in checked,
                on_change=lambda e, v=value: change(e, v)) for value in options if (find.value or '').casefold() in value.casefold()]
            self.page.update()
        find = ft.TextField(label='選択肢を絞り込み', on_change=redraw)
        def apply(event):
            setattr(self, attribute, checked)
            self.refresh_filter_labels()
            self.page.pop_dialog()
            self.page.update()
        def reset(event):
            checked.clear()
            redraw()
        dialog = ft.AlertDialog(title=ft.Text(title + '（複数選択・未選択はすべて）'),
            content=ft.Column([find, listing], tight=True), actions=[ft.TextButton('選択解除', on_click=reset),
            ft.TextButton('キャンセル', on_click=lambda e: self.page.pop_dialog()), ft.Button('適用', on_click=apply)])
        self.page.show_dialog(dialog)
        redraw()

    async def search(self, event=None):
        if self.normal.busy():
            return
        self.close_preview()
        self.progress.visible = True
        self.progress.value = None
        self.normal.set_busy(True, '構成部品表DBを読み込んでいます…')
        self.page.update()
        try:
            model = await self.ensure_catalog()
            conditions = dict(contains=self.query.value or '', excludes=self.exclude.value or '',
                              folders=set(self.folders), sheets=set(self.sheets), ids=self.ids.value or '',
                              start=self.start.value or '', end=self.end.value or '')
            def run(report):
                groups = model.search(**conditions, progress=report)
                report(('PDF索引を読み込んでいます…', None))
                warning = ''
                try:
                    _, paths = pdf_catalog.snapshot_paths(self.normal.index_database)
                except Exception as exc:
                    warning = f'PDF索引を利用できません：{exc}'
                else:
                    catalog.attach_pdfs(groups, paths, progress=report)
                return groups, warning
            self.results, warning = await self.run_search_worker(run)
            self.selection = set()
            self.active_key = None
            self.expanded_keys.clear()
            self.stock_view = False
            self.tabs.selected_index = 0
            self.scroll_offset = 0
            self.clear_preview()
            self.render()
            self.message(f'検索結果：{len(self.results)}部品' + (f' / {warning}' if warning else ''))
        except Exception as exc:
            self.message(f'検索できません：{exc}')
        finally:
            self.progress.visible = False
            self.normal.set_busy(False)
            self.page.update()
            if self.view.visible:
                await self.list.scroll_to(offset=0)
                await self.focus_navigation()

    async def run_search_worker(self, worker):
        import queue
        updates = queue.SimpleQueue()
        def report(update):
            updates.put(update)
        async def display():
            while True:
                await asyncio.sleep(0.1)
                latest = None
                while not updates.empty():
                    latest = updates.get_nowait()
                if latest:
                    self.normal.message.value, self.progress.value = latest
                    self.page.update()
        task = asyncio.create_task(display())
        try:
            return await asyncio.to_thread(worker, report)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def show_results(self, event=None):
        self.stock_view = False
        self.tabs.selected_index = 0
        self.close_preview()
        self.render()
        self.page.update()

    def show_stock(self, event=None):
        self.stock_view = True
        self.tabs.selected_index = 1
        self.close_preview()
        self.render()
        self.page.update()

    def on_tab_change(self, event=None):
        if self.normal.busy():
            return
        if self.tabs.selected_index == 1:
            self.show_stock()
        else:
            self.show_results()
        self.scroll_offset = 0
        self.page.run_task(self.reset_list_focus)

    async def reset_list_focus(self):
        await self.list.scroll_to(offset=0)
        await self.focus_navigation()

    async def commit(self, items):
        if self.load_error:
            self.message(self.load_error)
            return False
        try:
            # Small local atomic write; serialize UI mutations before yielding.
            stock.save(self.stock_path, items)
            self.items = items
            self.render()
            self.page.update()
        except Exception as exc:
            self.message(f'部品ストックを保存できません：{exc}')
            return False
        await self.focus_navigation()
        return True

    async def add_selected(self, event=None):
        if self.normal.busy():
            return
        groups = [g for g in self.results if g['key'] in self.selection]
        if not groups:
            self.message('追加する部品を選択してください')
            return
        if await self.commit(stock.add(self.items, groups)):
            self.message(f'{len(groups)}部品を部品ストックへ追加しました')

    async def select_all(self, event=None):
        await self.set_selection(True)

    async def select_none(self, event=None):
        await self.set_selection(False)

    async def invert_selection(self, event=None):
        await self.set_selection(None)

    async def set_selection(self, value):
        if self.normal.busy():
            return
        if self.stock_view:
            await self.commit([dict(item, selected=(not item['selected'] if value is None else value)) for item in self.items])
        else:
            keys = {g['key'] for g in self.results}
            self.selection = keys - self.selection if value is None else (keys if value else set())
            self.render()
            self.page.update()

        await self.focus_navigation()

    async def remove_selected(self, event=None):
        if self.normal.busy():
            return
        async def remove(e):
            self.page.pop_dialog()
            if await self.commit([i for i in self.items if not i['selected']]):
                self.clear_preview()
                self.page.update()
        self.page.show_dialog(ft.AlertDialog(title=ft.Text('選択した部品をストックから削除しますか？'),
            actions=[ft.TextButton('キャンセル', on_click=lambda e: self.page.pop_dialog()), ft.Button('削除', on_click=remove)]))

    async def move(self, key, offset):
        if self.normal.busy():
            return
        items = deepcopy(self.items)
        index = next(i for i, item in enumerate(items) if item['key'] == key)
        other = index + offset
        if 0 <= other < len(items):
            items[index], items[other] = items[other], items[index]
            await self.commit(items)

    def clear_preview(self):
        self.preview_generation += 1
        self.preview_group = None
        self.pdf_selection.clear()
        self.candidates.controls = []
        self.image.visible = False
        self.preview_label.value = '↑↓でプレビューする部品を移動できます'

    def close_preview(self):
        self.preview_panel.visible = False
        self.preview_button.content = SHOW_PDF_PREVIEW
        self.preview_hint.visible = False
        self.clear_preview()
        self.active_key = None
        self.highlight_active()

    def toggle_preview(self, event=None):
        if self.normal.busy():
            return
        self.preview_panel.visible = not self.preview_panel.visible
        if self.preview_panel.visible:
            self.preview_button.content = HIDE_PDF_PREVIEW
        else:
            self.close_preview()
        self.preview_hint.visible = self.preview_panel.visible
        self.resize_rows()
        self.page.update()
        if self.preview_panel.visible:
            self.page.run_task(self.open_preview, self.preview_generation)
        else:
            self.page.run_task(self.focus_navigation)

    async def open_preview(self, generation):
        if generation != self.preview_generation or not self.preview_panel.visible or not self.view.visible:
            return
        await self.focus_navigation()
        if generation != self.preview_generation or not self.preview_panel.visible or not self.view.visible:
            return
        if self.preview_group is None and self.groups():
            group = self.first_visible_group()
            await self.show_candidates(group)
        elif self.preview_group and not self.image.visible and self.preview_group['pdfs']:
            await self.preview(self.preview_group['pdfs'][0])

    async def show_candidates(self, group):
        if self.normal.busy():
            return
        self.clear_preview()
        self.preview_group = group
        self.active_key = group['key']
        self.preview_panel.visible = True
        self.preview_button.content = HIDE_PDF_PREVIEW
        self.preview_hint.visible = True
        self.preview_label.value = group['identifier'] + ' / ' + group['material'] + ' / ' + group['pdf_status']
        self.candidates.height = min(132, max(44, 44 * len(group['pdfs'])))
        for path in group['pdfs']:
            def check(event, path=path):
                if event.control.value:
                    self.pdf_selection.add(path)
                else:
                    self.pdf_selection.discard(path)
                self.page.run_task(self.focus_navigation)
            async def show(event, path=path):
                await self.preview(path)
                await self.focus_navigation()
            async def launch(event, path=path):
                await self.normal.open_pdf(path, False)
                await self.focus_navigation()
            self.candidates.controls.append(ft.Row([ft.Checkbox(on_change=check),
                ft.TextButton(Path(path).name, tooltip=path, on_click=show, expand=True),
                ft.IconButton(ft.Icons.OPEN_IN_NEW, tooltip='PDFを開く', on_click=launch)]))
        self.resize_rows()
        self.highlight_active()
        self.page.update()
        if group['pdfs']:
            await self.preview(group['pdfs'][0])

    async def preview(self, path):
        self.preview_generation += 1
        generation = self.preview_generation
        self.image.visible = False
        self.preview_label.value = f'読込中：{Path(path).name}'
        self.page.update()
        try:
            async with self.preview_lock:
                if generation != self.preview_generation:
                    return
                source = await asyncio.to_thread(self.normal.make_preview, path)
            if generation == self.preview_generation and self.preview_panel.visible and self.view.visible:
                self.image.src = source
                self.image.visible = True
                self.preview_label.value = Path(path).name
        except Exception as exc:
            if generation == self.preview_generation:
                self.preview_label.value = f'プレビューできません：{exc}'
        self.page.update()

    async def add_pdfs(self, event=None):
        if self.normal.busy():
            return
        if not self.pdf_selection:
            self.message('PDF候補のチェックを付けてください')
            return
        paths = [p for p in self.preview_group['pdfs'] if p in self.pdf_selection]
        if await self.normal.commit(add_to_stack(self.normal.items, paths)):
            self.message(f'{len(paths)}件をPDFストックへ追加しました。「PDFファイル名」モードで結合出力できます')

    async def open_occurrence(self, occurrence):
        if self.normal.busy():
            return
        self.normal.set_busy(True, '元Excelを読み取り専用で開いています…')
        self.page.update()
        try:
            shortcut = await asyncio.to_thread(create_sheet_shortcut, occurrence['path'], occurrence['sheet'], self.launch_directory.name)
            await self.launcher.launch_url(shortcut.as_uri(), mode=ft.LaunchMode.EXTERNAL_APPLICATION)
            self.message('元Excelの指定シートを読み取り専用で開く要求を送りました')
        except Exception as exc:
            self.message(f'元Excelを開けません：{exc}')
        finally:
            self.normal.set_busy(False)
            self.page.update()

    async def export(self, event=None):
        if self.normal.busy():
            return
        if not any(i['selected'] for i in self.items):
            self.message('出力する部品を選択してください')
            return
        folder = (self.normal.output_folder() or '').strip()
        if not folder or not Path(folder).is_dir():
            self.message('出力先フォルダを指定してください（上段のPDF出力先フォルダを共用します）')
            return
        self.normal.set_busy(True, '部品一覧Excelを作成しています…')
        self.page.update()
        try:
            target = Path(folder) / ('部品一覧_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.xlsx')
            await asyncio.to_thread(export_parts, deepcopy(self.items), target)
            self.message(f'部品一覧Excelを出力しました：{target}')
        except Exception as exc:
            self.message(f'部品一覧Excelを出力できません：{exc}')
        finally:
            self.normal.set_busy(False)
            self.page.update()

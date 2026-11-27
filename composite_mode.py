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
import pdf_catalog
from part_rules import DEFAULT_RULES
from update_age import format_updated
from composite_rows import CompositeRows
from normal_search import SearchLimitExceeded

SHOW_PDF_PREVIEW = 'PDFプレビューを表示'
HIDE_PDF_PREVIEW = 'PDFプレビューを閉じる'
PDF_CANDIDATE_HEIGHT = 44


class CompositeMode(CompositeRows):
    def __init__(self, page, normal, *, database=None, stock_path='part_stock.json', rules=DEFAULT_RULES,
                 button_style=None, selection_style=None):
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
        self.candidate_index = None
        self.navigating_candidates = False
        self.opening_candidate = False
        self.on_preview_visibility = None
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
        self.preview_hint = ft.Text('↑↓ 部品 ｜ Esc 閉じる', size=12, visible=False)
        self.result_tab = ft.Tab(label='検索結果')
        self.stock_tab = ft.Tab(label='部品ストック')
        self.add_button = ft.Button('部品ストックへ追加', on_click=self.add_selected, style=button_style)
        self.remove_button = ft.TextButton('選択部品を削除', on_click=self.remove_selected, visible=False)
        self.export_button = ft.Button('部品一覧Excel出力', on_click=self.export, visible=False)
        self.list_actions = [ft.Button('全選択', on_click=self.select_all, style=selection_style),
            ft.Button('全解除', on_click=self.select_none, style=selection_style),
            ft.Button('選択を反転', on_click=self.invert_selection, style=selection_style),
            self.add_button, self.remove_button, self.export_button]
        self.toolbar_actions = ft.Row([*self.list_actions, self.preview_hint, self.preview_button],
            alignment=ft.MainAxisAlignment.END, expand=True, wrap=True)
        self.toolbar = ft.Row([self.count, self.toolbar_actions], spacing=8)
        self.list = ft.ListView(expand=True, spacing=0, build_controls_on_demand=True)
        self.image = ft.Image(src='', fit=ft.BoxFit.CONTAIN, width=400, expand=True, visible=False)
        self.preview_label = ft.Text('↑↓でプレビューする部品を移動できます', selectable=True)
        self.candidates = ft.Stack(height=PDF_CANDIDATE_HEIGHT, clip_behavior=ft.ClipBehavior.HARD_EDGE, visible=False)
        self.preview_panel = ft.Container(ft.Column([
            self.preview_label, self.candidates, self.image,
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
        if not active and self.preview_panel.visible:
            self.close_preview()
            self.resize_rows()
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
        list_replaced = False
        try:
            model = await self.ensure_catalog()
            conditions = dict(contains=self.query.value or '', excludes=self.exclude.value or '',
                              folders=set(self.folders), sheets=set(self.sheets), ids=self.ids.value or '',
                              start=self.start.value or '', end=self.end.value or '')
            def run(report):
                groups = model.search(**conditions, progress=report, max_results=300)
                report(('PDF索引を読み込んでいます…', None))
                warning = ''
                try:
                    _, paths = pdf_catalog.snapshot_paths(self.normal.index_database)
                except Exception as exc:
                    warning = f'PDF索引を利用できません：{exc}'
                else:
                    catalog.attach_pdfs(groups, paths, progress=report)
                return groups, warning
            groups, warning = await self.run_search_worker(run)
            self.message('検索結果を表示しています…')
            self.replace_results(groups)
            list_replaced = True
            self.message(f'検索結果：{len(self.results)}部品' + (f' / {warning}' if warning else ''))
        except SearchLimitExceeded as exc:
            self.replace_results([])
            list_replaced = True
            self.message(str(exc))
        except Exception as exc:
            self.message(f'検索できません：{exc}')
        finally:
            self.progress.visible = False
            self.normal.set_busy(False)
            self.page.update()
            if self.view.visible and list_replaced:
                await self.list.scroll_to(offset=0)
                await self.focus_navigation()

    def replace_results(self, groups):
        self.results, self.selection = groups, set()
        self.active_key = None
        self.expanded_keys.clear()
        self.stock_view = False
        self.tabs.selected_index = 0
        self.scroll_offset = 0
        self.clear_preview()
        self.render()

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
        if self.preview_panel.visible:
            self.tabs.selected_index = int(self.stock_view)
            self.page.update()
            return
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
        self.candidate_index = None
        self.navigating_candidates = False
        self.candidates.controls = []
        self.candidates.visible = False
        self.preview_hint.value = '↑↓ 部品 ｜ Esc 閉じる'
        self.image.visible = False
        self.preview_label.value = '↑↓でプレビューする部品を移動できます'
        self.preview_label.visible = True

    def set_preview_visibility(self, visible):
        if self.preview_panel.visible == visible:
            return
        self.preview_panel.visible = visible
        self.filters.disabled = visible
        self.tab_bar.disabled = visible
        self.list_panel.disabled = visible
        for action in self.list_actions:
            action.disabled = visible
        self.update_list_actions()
        if self.on_preview_visibility is not None:
            self.on_preview_visibility(visible)

    def update_list_actions(self):
        show_actions = not self.preview_panel.visible
        for action in self.list_actions[:3]:
            action.visible = show_actions
        self.add_button.visible = show_actions and not self.stock_view
        self.remove_button.visible = self.export_button.visible = show_actions and self.stock_view

    def close_preview(self):
        self.key_repeat.stop()
        self.set_preview_visibility(False)
        self.preview_button.content = SHOW_PDF_PREVIEW
        self.preview_hint.visible = False
        self.clear_preview()
        self.active_key = None
        self.highlight_active()

    def toggle_preview(self, event=None):
        if self.normal.busy():
            return
        if not self.preview_panel.visible:
            self.set_preview_visibility(True)
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
        elif self.candidate_index is not None and not self.image.visible:
            await self.preview(self.preview_group['pdfs'][self.candidate_index])

    async def show_candidates(self, group):
        if self.normal.busy():
            return
        was_open = self.preview_panel.visible
        self.clear_preview()
        self.preview_group = group
        self.active_key = group['key']
        self.set_preview_visibility(True)
        self.preview_button.content = HIDE_PDF_PREVIEW
        self.preview_hint.visible = True
        self.preview_label.value = group['identifier'] + ' / ' + group['material'] + ' / ' + group['pdf_status']
        paths = group['pdfs']
        self.candidates.visible = bool(paths)
        self.preview_label.visible = not paths
        if not was_open:
            self.resize_rows()
        self.highlight_active()
        if paths:
            self.set_candidate_navigation(False)
            await self.select_candidate(0)
        else:
            self.page.update()

    def set_candidate_navigation(self, active):
        self.navigating_candidates = active
        multiple = self.preview_group and len(self.preview_group['pdfs']) > 1
        movement = ('↑↓ PDF候補 ｜ ← 部品へ' if active else
                    '↑↓ 部品 ｜ → PDF候補へ' if multiple else '↑↓ 部品')
        self.preview_hint.value = movement + ' ｜ Enter PDFを開く ｜ Esc 閉じる'
        self.highlight_candidate()

    async def open_selected_candidate(self):
        if self.candidate_index is not None:
            await self.open_candidate(self.candidate_index)

    async def open_candidate(self, index):
        if not self.can_navigate() or self.preview_group is None:
            return
        if self.preview_group['key'] != self.active_key:
            return
        path = self.preview_group['pdfs'][index]
        self.opening_candidate = True
        self.key_repeat.stop()
        try:
            await self.normal.open_pdf(path, False)
        finally:
            self.opening_candidate = False

    def candidate_card(self, group, index):
        path = group['pdfs'][index]

        async def show(event):
            if self.preview_group is group and self.can_navigate():
                self.set_candidate_navigation(len(group['pdfs']) > 1)
                await self.select_candidate(index)
                await self.focus_navigation()

        async def launch(event):
            if self.preview_group is group:
                await self.open_candidate(index)
                await self.focus_navigation()

        number = chr(0x2460 + index) if index < 20 else f'{index + 1}.'
        name = ft.Text(f'{number} {Path(path).name}', max_lines=1, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS)
        controls = [ft.TextButton(name, tooltip=path, on_click=show, expand=True)]
        if index == self.candidate_index:
            controls.append(ft.IconButton(ft.Icons.OPEN_IN_NEW, tooltip='PDFを開く', on_click=launch, width=36))
        alignment = ft.Alignment.CENTER_RIGHT if index < self.candidate_index else ft.Alignment.CENTER_LEFT
        return ft.Container(ft.Row(controls, spacing=0), alignment=alignment,
            data=index, top=0, height=PDF_CANDIDATE_HEIGHT, border_radius=4,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT))

    def layout_candidates(self):
        if self.candidate_index is None:
            return
        width = max(0, (self.preview_panel.width or 420) - 16)
        multiple = len(self.preview_group['pdfs']) > 1
        card_width = width * .62 if multiple else width
        center = (width - card_width) / 2
        for card in self.candidates.controls:
            card.width = card_width
            card.left = center + (card.data - self.candidate_index) * (card_width + 8)
            card.content.width = card_width if card.data == self.candidate_index else max(0, center - 8)

    def highlight_candidate(self):
        color = ft.Colors.PRIMARY_CONTAINER if self.navigating_candidates else ft.Colors.SECONDARY_CONTAINER
        for card in self.candidates.controls:
            card.bgcolor = color if card.data == self.candidate_index else None

    async def select_candidate(self, index):
        group = self.preview_group
        if index == self.candidate_index:
            self.page.update()
            return
        self.candidate_index = index
        # Only immediate neighbours are needed to show which ways the user can move.
        visible_indices = range(max(0, index - 1), min(len(group['pdfs']), index + 2))
        self.candidates.controls = [self.candidate_card(group, candidate) for candidate in visible_indices]
        self.layout_candidates()
        self.highlight_candidate()
        await self.preview(group['pdfs'][index])

    async def preview(self, path):
        self.preview_generation += 1
        generation = self.preview_generation
        self.image.visible = False
        self.preview_label.visible = False
        self.page.update()
        try:
            async with self.preview_lock:
                if generation != self.preview_generation:
                    return
                source = await asyncio.to_thread(self.normal.make_preview, path)
            if generation == self.preview_generation and self.preview_panel.visible and self.view.visible:
                self.image.src = source
                self.image.visible = True
        except Exception as exc:
            if generation == self.preview_generation:
                self.preview_label.value = f'プレビューできません：{exc}'
                self.preview_label.visible = True
        self.page.update()

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

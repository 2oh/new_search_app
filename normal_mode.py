"""Normal search UI. Shared PDF operations are supplied by the existing app."""
import asyncio
from datetime import datetime
import os
from pathlib import Path
import uuid

import flet as ft
import flet_datatable2 as dt2
import pdf_catalog
from update_age import format_updated
from normal_search import StackStore, add_to_stack, file_info, parse_search_query, path_key, search_files
from normal_preview import NormalPreview
from pdf_folder_filter import FolderFilter


PDF_RESULT_LIMIT = 500


class NormalMode(NormalPreview):
    def __init__(self, page, *, folder, output_folder, collect, preview, open_pdf,
                 merge, busy, set_busy, worker, message, completed, version, button_style,
                 index_database=None, index_publish='', save_publish=None, selection_style=None):
        self.page = page
        self.folder, self.output_folder = folder, output_folder
        self.collect, self.make_preview, self.open_pdf, self.merge = collect, preview, open_pdf, merge
        self.busy, self.set_busy, self.worker = busy, set_busy, worker
        self.message, self.completed, self.version = message, completed, version
        self.index_database = Path(index_database) if index_database else Path(
            os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'DrawingPdfSearch' / 'pdf_catalog.sqlite'
        self.index_root = ''
        self.folder = lambda: self.index_root
        self.save_publish = save_publish
        self.sync_status = ft.Text(size=12, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)
        self.selection_lock = asyncio.Lock()
        self.pending_selection = 0
        self.selection_boxes = {False: {}, True: {}}
        self.sync_other = None
        self.on_sync_finished = None
        self.on_sync_started = None
        self.on_pdf_updated = None
        self.publish_field = ft.TextField(label='PDF索引データ配信元フォルダ', value=index_publish,
                                         width=480, on_change=self.on_publish_change)
        self.index_label = ft.Text('PDF索引DBは未取得です', size=12, max_lines=3,
                                   overflow=ft.TextOverflow.ELLIPSIS)
        self.root_field = ft.TextField(label='PDF検索先フォルダ', value='',
                                      read_only=True, expand=True, can_request_focus=False,
                                      enable_interactive_selection=False, show_cursor=False,
                                      bgcolor=ft.Colors.SECONDARY_CONTAINER, color=ft.Colors.ON_SECONDARY_CONTAINER,
                                      border=ft.OutlineInputBorder(side=ft.BorderSide(1, ft.Colors.BLUE_400)),
                                      label_style=ft.TextStyle(color=ft.Colors.ON_SECONDARY_CONTAINER))
        self.root_display = ft.Container(self.root_field, width=480, ignore_interactions=True,
            tooltip='索引データから取得した検索先です。ここでは編集できません。')
        self.sync_button = ft.Button('最新データ取得', on_click=self.sync_index, style=button_style)
        self.publish_picker = ft.FilePicker()
        self.publish_button = ft.Button('フォルダを選択', on_click=self.pick_publish, style=button_style)
        self.index_controls = ft.Row([
            self.publish_field, self.publish_button, self.sync_button,
            ft.Container(self.index_label, expand=True),
        ], spacing=8, expand=True)
        self.resize_settings()
        self.refresh_index_label()
        self.store = StackStore('normal_stack.json')
        self.load_error = ''
        try:
            self.items = self.store.load()
        except (OSError, ValueError) as exc:
            self.items = []
            self.load_error = f'ストックを読み込めません。保存データを保護するため変更を停止しています：{exc}'
        self.results, self.selection, self.metadata = [], set(), {}
        self.folder_matches, self.folder_selection = None, set()
        self.match_count = self.filtered_count = 0
        self.loaded_terms = None
        self.files, self.index_folder = None, None
        self.preview_generation = 0
        self.activation_generation = 0
        self.preview_running = False
        self.preview_pending = None
        self.query = ft.TextField(label='検索文字列', hint_text='空白区切り（例：A B）でAND検索。ファイル名内のA・Bの出現順に関係なく検索されます。空白を含む文字列は " " で囲みます（例："ab c"）。',
                                  expand=True, on_submit=self.search, on_focus=self.caret_end)
        self.exclude = ft.TextField(label='除く文字列', hint_text='空白区切り・いずれか一致で除外', expand=True, on_submit=self.search)
        self.search_button = ft.Button('検索', on_click=self.search, style=button_style)
        self.query.tooltip = self.query.hint_text
        self.search_indicator = ft.ProgressBar(width=160, height=6, value=None, visible=False)
        self.folder_filter = FolderFilter(page, PDF_RESULT_LIMIT)
        self.folder_button = ft.OutlinedButton('フォルダで絞り込み', icon=ft.Icons.ARROW_DROP_DOWN,
                                               on_click=self.choose_folders)
        self.query.on_change = self.exclude.on_change = self.on_search_text_change
        self.search_controls = ft.Column([ft.Row([self.query]), ft.Row([self.exclude]),
                                          ft.Row([self.folder_button])], expand=True, spacing=6)
        self.result_count = ft.Text('検索結果：0件', weight=ft.FontWeight.BOLD)
        self.stack_count = ft.Text('', weight=ft.FontWeight.BOLD)
        self.export_button = ft.Button('PDF出力', on_click=self.export, style=button_style)
        self.open_button = ft.Button('PDFを開く', on_click=self.open_selected, style=button_style)
        self.result_table = self.new_table()
        self.stack_table = self.new_table()
        self.init_preview()
        self.result_listing = ft.Container(self.result_table, expand=True)
        self.stock_listing = ft.Container(self.stack_table, expand=True)
        self.result_actions = ft.Row([
            ft.Button('全選択', on_click=self.select_all, style=selection_style),
            ft.Button('全解除', on_click=self.deselect_all, style=selection_style),
            ft.Button('選択を反転', on_click=self.invert_results, style=selection_style),
            ft.Button('ストックへ追加', on_click=self.add_selected, style=button_style)], tight=True)
        self.stock_actions = ft.Row([
            ft.Button('全選択', on_click=self.check_all, style=selection_style),
            ft.Button('全解除', on_click=self.uncheck_all, style=selection_style),
            ft.Button('選択を反転', on_click=self.invert_stock, style=selection_style),
            ft.TextButton('全削除', on_click=self.confirm_clear),
            self.open_button, self.export_button], tight=True, visible=False)
        self.stack_count.visible = False
        self.toolbar_actions = ft.Row([self.result_actions, self.stock_actions, self.preview_target,
            self.preview_hint, self.preview_button], alignment=ft.MainAxisAlignment.END, expand=True, wrap=True)
        self.toolbar = ft.Row([self.result_count, self.stack_count, self.toolbar_actions], spacing=8)
        self.result_tab = ft.Tab(label='検索結果')
        self.stack_tab = ft.Tab(label='ストック')
        self.tab_bar = ft.TabBar(tabs=[self.result_tab, self.stack_tab])
        self.tab_content = ft.TabBarView(controls=[
            ft.Container(self.result_listing, padding=6),
            ft.Container(self.stock_listing, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST, padding=6),
        ])
        # The preview has a permanent parent outside TabBarView. Swapping the
        # child of a tab page while Flutter is building it can leave it blank.
        self.lists = ft.Stack([self.tab_content, self.preview_listing], expand=True, fit=ft.StackFit.EXPAND)
        self.image = ft.Image(src='', fit=ft.BoxFit.CONTAIN, expand=True, visible=False)
        self.preview_label = ft.Text('', size=14, color=ft.Colors.PRIMARY,
                                     weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER)
        self.preview_panel = ft.Container(content=ft.Column([self.preview_label, self.image],
            expand=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=8, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST, visible=False)
        self.body = ft.Row([self.lists, self.preview_panel], expand=True,
                           vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        self.tabs = ft.Tabs(length=2, selected_index=0, expand=True, on_change=self.on_tab_change,
            content=ft.Column([self.tab_bar, self.toolbar, self.body], expand=True, spacing=4))
        self.view = ft.Container(content=self.tabs, expand=True, visible=False)
        self.render()

    def on_publish_change(self, event=None):
        if self.save_publish:
            self.save_publish(self.publish_field.value or '')

    def resize_settings(self):
        self.publish_field.width = max(280, min(620, (self.page.width or 1400) - 240))
        self.root_display.width = max(400, min(1000, (self.page.width or 1400) - 720))

    async def pick_publish(self, event=None):
        if self.busy():
            return
        initial = (self.publish_field.value or '').strip()
        selected = await self.publish_picker.get_directory_path(initial_directory=initial or None)
        if selected and not self.busy():
            self.publish_field.value = selected
            self.on_publish_change()
            self.page.update()

    def refresh_index_label(self):
        try:
            info = pdf_catalog.metadata(self.index_database)
            self.index_root = info['root']
            self.root_field.value = self.index_root
            self.root_field.tooltip = self.index_root
            updated = format_updated(info['updated'])
            self.index_label.value = f'PDF索引：{updated}　{info["count"]}件'
        except Exception:
            self.index_root = ''
            self.root_field.value = ''
            self.root_field.tooltip = None
            self.index_label.value = 'PDF索引：未取得（設定から配信元を指定してください）'
        self.index_label.tooltip = self.index_label.value

    async def sync_index(self, event=None):
        if self.busy():
            return
        self.close_folder_filter()
        folder = (self.publish_field.value or '').strip()
        if not folder:
            self.report_error('PDF索引データ配信元フォルダを指定してください。')
            return
        if self.on_sync_started:
            self.on_sync_started()
        self.set_busy(True)
        self.sync_status.value = '検索データの最新版を確認しています…'
        self.index_controls.disabled = True
        self.page.update()
        try:
            changed = await asyncio.to_thread(pdf_catalog.sync, folder, self.index_database)
            self.refresh_index_label()
            if changed:
                self.activation_generation += 1
                self.results, self.selection = [], set()
                self.folder_matches, self.folder_selection = None, set()
                self.match_count = self.filtered_count = 0
                self.loaded_terms = None
                self.files = None
                self.clear_preview()
            if changed and self.on_pdf_updated:
                self.on_pdf_updated()
            self.sync_status.value = 'PDF索引の最新データを取得しました。' if changed else '配信済みの最新版と一致'
        except Exception as exc:
            self.refresh_index_label()
            suffix = '前回取得したDBで検索できます。' if self.index_root else '検索用DBは利用できません。'
            self.index_label.value += f' / 最新版取得失敗：{suffix}'
            self.index_label.tooltip = self.index_label.value
            self.sync_status.value = f'PDF索引を取得できませんでした：{exc} {suffix}'
        finally:
            if self.sync_other:
                other_status = await self.sync_other(folder)
                # The BOM result is displayed on its own row.
            self.index_controls.disabled = False
            self.set_busy(False)
            self.render()
            self.sync_status.tooltip = self.sync_status.value
            self.page.update()
            if self.on_sync_finished:
                await self.on_sync_finished()

    async def startup_sync(self):
        if (self.publish_field.value or '').strip():
            # Avoid replacing a DB while another app operation owns the shared busy flag.
            while self.busy():
                await asyncio.sleep(0.1)
            await self.sync_index()

    @staticmethod
    def new_table():
        return dt2.DataTable2(columns=[ft.DataColumn(ft.Text('PDF'))], rows=[],
                              fixed_top_rows=1, data_row_height=72, heading_row_height=48,
                              heading_row_color=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                              column_spacing=8, horizontal_margin=8, min_width=620,
                              visible_horizontal_scroll_bar=True, visible_vertical_scroll_bar=True)

    def caret_end(self, event=None):
        offset = len((self.query.value or '').encode('utf-16-le')) // 2
        self.query.selection = ft.TextSelection(base_offset=offset, extent_offset=offset)
        self.page.update()

    async def focus(self):
        if self.view.visible and not self.busy() and not self.preview_panel.visible:
            await self.query.focus()
            self.caret_end()

    def clear_preview(self):
        self.preview_generation += 1
        self.preview_pending = None
        self.image.visible = False
        self.preview_label.value = ''

    def on_tab_change(self, event=None):
        self.close_preview()
        self.update_tab_actions()
        self.page.update()

    def update_tab_actions(self):
        stock = self.tabs.selected_index == 1
        show_actions = not self.preview_panel.visible
        self.stack_count.visible = stock
        self.result_count.visible = not stock
        self.stock_actions.visible = stock and show_actions
        self.folder_button.visible = show_actions
        self.result_actions.visible = not stock and show_actions

    def activate(self, active):
        if not active:
            self.close_preview()
            self.close_folder_filter()
        self.activation_generation += 1
        self.view.visible = active
        self.preview_generation += 1
        self.preview_pending = None
        if active:
            self.refresh_index_label()
            self.resize()
            self.message.value = self.load_error or self.folder_result_message()
            self.page.run_task(self.activate_async)

    async def activate_async(self):
        generation = self.activation_generation
        await self.focus()
        paths = [i['path'] for i in self.items]
        if paths:
            metadata = await asyncio.to_thread(lambda: {path_key(p): file_info(p) for p in paths})
            if generation != self.activation_generation or not self.view.visible:
                return
            self.metadata.update(metadata)
            self.render()
            self.page.update()

    def resize(self):
        if self.preview_panel.visible:
            self.preview_viewport = None
            self.set_preview_layout()
        self.render()

    def table_path_width(self):
        return min(600, max(450, (self.page.width or 1200) - 960))

    def report_error(self, exc):
        self.message.value = str(exc)
        self.page.update()

    async def search(self, event=None):
        if self.busy():
            return
        self.close_preview()
        self.close_folder_filter()
        try:
            terms = self.search_terms()
        except ValueError as exc:
            self.report_error(exc)
            await self.focus()
            return
        if not terms[0] and not self.folder_selection:
            self.report_error('検索文字列を入力するか、フォルダを選択してください。')
            await self.focus()
            return
        try:
            matches = await self.scan_folders(terms)
        except Exception as exc:
            self.report_error(f'検索できませんでした：{exc}')
            return
        self.selection.clear()
        self.install_matches(matches, terms)
        self.apply_folder_filter(self.folder_selection)
        if self.filtered_count > PDF_RESULT_LIMIT:
            self.open_folder_filter(matches, terms)
        else:
            self.page.run_task(self.focus)

    def search_terms(self):
        return (tuple(parse_search_query(self.query.value)), tuple(parse_search_query(self.exclude.value)))

    async def scan_folders(self, terms):
        self.search_indicator.value = None
        self.search_indicator.visible = True
        self.set_busy(True, 'PDF索引を検索中…')
        self.activation_generation += 1
        try:
            def work(report):
                return pdf_catalog.search_folders(self.index_database, terms[0], lambda current, total: report((
                    f'ファイル名を検索中：{current}/{total}件', current / total if total else 1.0)),
                    excludes=terms[1], allow_empty=True)
            _, matches = await self.worker(work)
            return matches
        finally:
            self.search_indicator.visible = False
            self.set_busy(False)
            self.page.update()

    def install_matches(self, matches, terms):
        self.index_root = str(matches.root)
        self.files, self.index_folder = None, path_key(self.index_root)
        self.folder_matches, self.loaded_terms = matches, terms
        self.match_count = matches.count(set())

    def folder_result_message(self):
        if self.filtered_count > PDF_RESULT_LIMIT:
            return f'検索結果が{PDF_RESULT_LIMIT}件を超えました（対象{self.filtered_count:,}件）。条件を絞ってください'
        return f'検索結果：{len(self.results):,}件' + (
            f'（全{self.match_count:,}件から絞り込み）' if self.folder_selection else '')

    async def choose_folders(self, event=None):
        if self.busy() or self.preview_panel.visible:
            return
        if self.folder_filter.panel.visible:
            self.dismiss_folder_filter()
            return
        try:
            terms = self.search_terms()
            matches = self.folder_matches if self.loaded_terms == terms else await self.scan_folders(terms)
        except Exception as exc:
            self.report_error(f'フォルダを読み込めません：{exc}')
            return
        self.message.value = self.folder_result_message()
        self.open_folder_filter(matches, terms)

    def open_folder_filter(self, matches, terms):
        def apply(selection):
            if self.busy() or self.preview_panel.visible:
                return
            if self.folder_matches is not matches:
                self.selection.clear()
                self.install_matches(matches, terms)
            self.close_folder_filter()
            self.apply_folder_filter(selection)

        self.folder_button.icon = ft.Icons.ARROW_DROP_UP
        self.folder_filter.open(matches, self.folder_selection, require_folder=not terms[0],
                                on_apply=apply, on_close=self.dismiss_folder_filter)

    def close_folder_filter(self):
        self.folder_filter.close()
        self.folder_button.icon = ft.Icons.ARROW_DROP_DOWN

    def dismiss_folder_filter(self):
        self.close_folder_filter()
        self.page.update()

    def on_search_text_change(self, event):
        if self.folder_filter.panel.visible:
            self.dismiss_folder_filter()

    def apply_folder_filter(self, selected):
        self.folder_selection = set(selected)
        self.filtered_count, self.results = self.folder_matches.results(selected, PDF_RESULT_LIMIT)
        self.tabs.selected_index = 0
        self.update_tab_actions()
        self.metadata.update({path_key(item['path']): item for item in self.results})
        self.render(results_only=True)
        self.message.value = self.folder_result_message()
        self.page.update()

    @staticmethod
    def header(label, count=None, color=ft.Colors.SECONDARY):
        title = ft.Text(label, size=12, weight=ft.FontWeight.BOLD)
        if count is None:
            return title
        return ft.Row([title, ft.Container(ft.Text(str(count), size=12,
            color=ft.Colors.ON_SECONDARY if color == ft.Colors.SECONDARY else ft.Colors.ON_PRIMARY, weight=ft.FontWeight.BOLD),
            padding=ft.Padding.symmetric(horizontal=7, vertical=3), border_radius=12,
            bgcolor=color)], spacing=4, alignment=ft.MainAxisAlignment.CENTER)

    def folder_label(self, path):
        try:
            relative = os.path.relpath(str(Path(path).parent), self.folder().strip())
            return '（検索先直下）' if relative == '.' else relative
        except (ValueError, OSError):
            return str(Path(path).parent)

    def render(self, results_only=False):
        stacked = {path_key(item['path']) for item in self.items}
        self.selection.difference_update(stacked)
        output_count = sum(i['selected'] for i in self.items)
        self.update_result_count()
        self.folder_button.disabled = self.preview_panel.visible
        self.folder_button.content = (f'フォルダで絞り込み（{len(self.folder_selection)}）'
                                      if self.folder_selection else 'フォルダで絞り込み')
        self.folder_button.tooltip = '\n'.join(' / '.join(folder) or '（検索先直下）'
                                               for folder in sorted(self.folder_selection)) or None
        self.stack_count.value = f'ストック：{len(self.items)}件'
        self.result_tab.label = self.header('検索結果', len(self.results), ft.Colors.PRIMARY)
        self.stack_tab.label = self.header('ストック', len(self.items), ft.Colors.PRIMARY)
        self.export_button.disabled = self.busy() or self.pending_selection > 0 or not output_count or bool(self.load_error)
        self.open_button.disabled = self.export_button.disabled
        path_width = self.table_path_width()
        for table, items, is_stack in ((self.result_table, self.results, False), (self.stack_table, self.items, True)):
            if results_only and is_stack:
                continue
            self.selection_boxes[is_stack] = {}
            columns = [('項番', 46), ('パス', path_width), ('ファイル名', None), ('更新日時', 96)]
            if is_stack:
                columns.append(('削除', 64))
            columns.append(('選択' if is_stack else '追加', 100))
            table.min_width = sum(width or 360 for _, width in columns) + 16
            table.columns = [dt2.DataColumn2(self.header(label,
                (output_count if is_stack else len(self.selection & self.result_keys())) if index == len(columns)-1 else None,
                ft.Colors.SECONDARY if is_stack else ft.Colors.PRIMARY), fixed_width=width)
                for index, (label, width) in enumerate(columns)]
            rows = []
            for number, item in enumerate(items, 1):
                path = item['path']
                key = path_key(path)
                meta = self.metadata.get(key, item)
                async def change(e, key=key, is_stack=is_stack):
                    await self.set_row_check(is_stack, key, bool(e.control.value))
                checkbox = ft.Checkbox(value=item['selected'] if is_stack else key in self.selection,
                    disabled=bool(self.load_error) or (not is_stack and key in stacked), on_change=change)
                self.selection_boxes[is_stack][key] = checkbox
                async def open_file(e, path=path):
                    self.caret_end()
                    await self.open_pdf(path, False)
                async def open_folder(e, path=path):
                    self.caret_end()
                    await self.open_pdf(path, True)
                async def remove(e, key=key):
                    await self.commit([dict(i) for i in self.items if path_key(i['path']) != key])
                label = Path(path).name
                status = '（参照不可）' if meta.get('available') is False else ''
                def link(value, click, color, tooltip, lines=1):
                    return ft.Container(ft.Text(value, size=14, color=color,
                        no_wrap=lines == 1, max_lines=lines, overflow=ft.TextOverflow.ELLIPSIS),
                        on_click=click, ink=True, tooltip=tooltip,
                        alignment=ft.Alignment.CENTER_LEFT)
                folder = self.folder_label(path)
                modified = meta.get('modified')
                date = datetime.fromtimestamp(modified).strftime('%Y/%m/%d\n%H:%M') if modified is not None else '—'
                def centered(control):
                    return ft.DataCell(ft.Container(control, alignment=ft.Alignment.CENTER))
                cells = [centered(ft.Text(str(number), size=14)),
                    ft.DataCell(link(folder, open_folder, ft.Colors.ON_SURFACE, str(Path(path).parent))),
                    ft.DataCell(link(label + status, open_file, ft.Colors.PRIMARY, path + status, lines=2)),
                    ft.DataCell(ft.Text(date, size=14, no_wrap=True, max_lines=2))]
                if is_stack:
                    cells.append(centered(ft.IconButton(icon=ft.Icons.DELETE_OUTLINE,
                        icon_color=ft.Colors.ORANGE_300, tooltip='ストックから削除',
                        on_click=remove, disabled=bool(self.load_error))))
                if not is_stack and key in stacked:
                    checkbox.tooltip = '既にPDFストックに登録済みです。ストック側で選択・出力できます。'
                    cells.append(centered(self.stocked_checkbox(checkbox)))
                else:
                    cells.append(centered(checkbox))
                rows.append(ft.DataRow(cells=cells))
            table.rows = rows

    @staticmethod
    def stocked_checkbox(checkbox):
        return ft.Column([ft.Container(checkbox, height=30),
                          ft.Text('ストック済', size=12, color=ft.Colors.PRIMARY)],
            spacing=0, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER)

    async def set_row_check(self, is_stack, key, value):
        if self.busy() or self.load_error:
            return
        if is_stack:
            await self.save_selection(value, key)
        elif not self.selection_boxes[False][key].disabled:
            self.selection.add(key) if value else self.selection.discard(key)
            self.refresh_selection()
            self.page.update()

    def refresh_selection(self):
        count = sum(item['selected'] for item in self.items)
        self.update_result_count()
        self.export_button.disabled = self.open_button.disabled = bool(
            self.busy() or self.pending_selection or not count or self.load_error)
        for is_stack, table in ((False, self.result_table), (True, self.stack_table)):
            values = {path_key(i['path']): i['selected'] for i in self.items} if is_stack else {
                key: key in self.selection for key in self.selection_boxes[False]}
            for key, checkbox in self.selection_boxes[is_stack].items():
                checkbox.value = values.get(key, False)
            if self.preview_panel.visible and self.preview_stock == is_stack:
                for key, checkbox in self.preview_checks.items():
                    checkbox.value = values.get(key, False)
            if table.columns:
                table.columns[-1].label = self.header('選択' if is_stack else '追加',
                    count if is_stack else len(self.selection & self.result_keys()),
                    ft.Colors.SECONDARY if is_stack else ft.Colors.PRIMARY)

    async def save_selection(self, value, key=None):
        if self.busy() or self.load_error:
            self.refresh_selection()
            self.page.update()
            return False
        self.pending_selection += 1
        self.export_button.disabled = self.open_button.disabled = True
        self.page.update()
        try:
            async with self.selection_lock:
                items = [dict(i, selected=(not i['selected'] if value is None else value)) if key is None or path_key(i['path']) == key else dict(i)
                         for i in self.items]
                await asyncio.to_thread(self.store.save, items)
                self.items = items
            return True
        except Exception as exc:
            self.message.value = f'選択を保存できませんでした。前の状態へ戻します：{exc}'
            return False
        finally:
            self.pending_selection -= 1
            self.refresh_selection()
            self.page.update()

    async def commit(self, items):
        if self.busy() or self.pending_selection or self.load_error:
            if self.load_error:
                self.report_error(self.load_error)
            return False
        self.set_busy(True, 'ストックに保存しています…')
        saved = False
        try:
            await asyncio.to_thread(self.store.save, items)
            self.items = items
            saved = True
            self.message.value = 'ストックに保存しました。'
        except Exception as exc:
            self.message.value = f'保存できなかったため変更を取り消しました：{exc}'
        finally:
            self.set_busy(False)
            self.render()
            self.page.update()
        return saved

    async def add_selected(self, e=None):
        if self.busy():
            return
        paths = [i['path'] for i in self.results if path_key(i['path']) in self.selection]
        if not paths:
            self.report_error('ストックに追加するPDFをチェックしてください。')
            return
        await self.commit(add_to_stack(self.items, paths))

    def result_keys(self):
        return {path_key(item['path']) for item in self.results}

    def update_result_count(self):
        hidden = len(self.selection - self.result_keys())
        self.result_count.value = f'検索結果：{len(self.results):,}件' + (
            f'（非表示のチェック {hidden:,}件）' if hidden else '')

    def select_all(self, e=None):
        if self.busy():
            return
        stacked = {path_key(i['path']) for i in self.items}
        self.selection.update(self.result_keys() - stacked)
        self.refresh_selection()
        self.page.update()

    def deselect_all(self, e=None):
        if not self.busy():
            self.selection.difference_update(self.result_keys())
            self.refresh_selection()
            self.page.update()

    def invert_results(self, e=None):
        if self.busy():
            return
        stacked = {path_key(i['path']) for i in self.items}
        eligible = self.result_keys() - stacked
        self.selection.symmetric_difference_update(eligible)
        self.refresh_selection()
        self.page.update()

    async def invert_stock(self, e=None):
        await self.save_selection(None)

    async def check_all(self, e=None):
        await self.save_selection(True)

    async def uncheck_all(self, e=None):
        await self.save_selection(False)

    def confirm_clear(self, e=None):
        if self.busy() or self.load_error or not self.items:
            return
        async def yes(e):
            dialog.open = False
            await self.commit([])
        def no(e):
            dialog.open = False
            self.page.update()
        dialog = ft.AlertDialog(modal=True, title=ft.Text('ストックを全削除しますか？'),
                                content=ft.Text('元のPDFファイルは削除しません。'),
                                actions=[ft.TextButton('キャンセル', on_click=no), ft.TextButton('全削除', on_click=yes)])
        self.page.show_dialog(dialog)

    def request_preview(self, path):
        if not self.can_navigate():
            return
        self.preview_generation += 1
        self.preview_pending = (self.preview_generation, path)
        self.image.visible = False
        self.preview_label.value = f'読込中：{Path(path).name}'
        self.page.update()
        if not self.preview_running:
            self.page.run_task(self.preview_loop)

    async def preview_loop(self):
        if self.preview_running:
            return
        self.preview_running = True
        try:
            while self.preview_pending:
                generation, path = self.preview_pending
                self.preview_pending = None
                try:
                    preview = await asyncio.to_thread(self.make_preview, path)
                    if generation == self.preview_generation and self.view.visible:
                        self.image.src = preview
                        self.image.visible = True
                        self.preview_label.value = Path(path).name
                except Exception as exc:
                    if generation == self.preview_generation:
                        self.preview_label.value = f'プレビューできません：{exc}'
                        self.image.visible = False
                self.page.update()
        finally:
            self.preview_running = False

    async def open_selected(self, event=None):
        if self.busy() or self.pending_selection or self.load_error:
            return
        paths = [item['path'] for item in self.items if item['selected']]
        if not paths:
            self.report_error('開くPDFを選択してください。')
            return
        self.caret_end()
        self.set_busy(True, '選択したPDFを開いています…')
        opened, failed = 0, []
        try:
            for path in paths:
                try:
                    success = await self.open_pdf(path, False, batch=True)
                    if success is False:
                        failed.append(path)
                    else:
                        opened += 1
                except Exception:
                    failed.append(path)
            self.message.value = f'PDFを開く操作を実行しました：{opened}件。'
            if failed:
                self.message.value += f' 開けなかったPDF：{len(failed)}件\n' + '\n'.join(failed)
        finally:
            self.set_busy(False)
            self.render()
            self.page.update()

    async def export(self, event=None):
        if self.busy() or self.pending_selection or self.load_error:
            return
        paths = [item['path'] for item in self.items if item['selected']]
        if not paths:
            self.report_error('出力対象のPDFがありません。')
            return
        folder = self.output_folder().strip()
        if not folder:
            self.report_error('出力先フォルダを指定してください。')
            return
        self.search_indicator.value = None
        self.search_indicator.visible = True
        self.set_busy(True, '出力するPDFを確認中…')
        try:
            def work(report):
                missing = [path for path in paths if not Path(path).is_file()]
                if missing:
                    raise FileNotFoundError('参照できないPDFがあります。出力を中止しました：' + '\n'.join(missing))
                output = Path(folder)
                output.mkdir(parents=True, exist_ok=True)
                name = f'通常検索_{datetime.now():%Y%m%d_%H%M%S_%f}_{self.version}.pdf'
                target = output / name
                temporary = output / f'.normal-{uuid.uuid4().hex}.tmp'
                try:
                    self.merge(paths, str(temporary), lambda i, total, path: report((f'PDF結合中：{i}/{total}件', i / total if total else 1.0)))
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
                return str(target)
            target = await self.worker(work)
            self.message.value = f'PDFを出力しました：{target}'
            self.completed(self.message.value)
        except Exception as exc:
            self.message.value = f'PDFを出力できませんでした：{exc}'
        finally:
            self.search_indicator.visible = False
            self.set_busy(False)
            self.render()
            self.page.update()

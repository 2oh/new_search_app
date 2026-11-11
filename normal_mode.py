"""Normal search UI. Shared PDF operations are supplied by the existing app."""
import asyncio
from datetime import datetime
import os
from pathlib import Path
import uuid

import flet as ft
import flet_datatable2 as dt2
from normal_search import StackStore, add_to_stack, file_info, parse_search_query, path_key, search_files


class NormalMode:
    def __init__(self, page, *, folder, output_folder, collect, preview, open_pdf,
                 merge, busy, set_busy, worker, message, completed, version, button_style):
        self.page = page
        self.folder, self.output_folder = folder, output_folder
        self.collect, self.make_preview, self.open_pdf, self.merge = collect, preview, open_pdf, merge
        self.busy, self.set_busy, self.worker = busy, set_busy, worker
        self.message, self.completed, self.version = message, completed, version
        self.store = StackStore('normal_stack.json')
        self.load_error = ''
        try:
            self.items = self.store.load()
        except (OSError, ValueError) as exc:
            self.items = []
            self.load_error = f'ストックを読み込めません。保存データを保護するため変更を停止しています：{exc}'
        self.results, self.selection, self.metadata = [], set(), {}
        self.files, self.index_folder = None, None
        self.preview_generation = 0
        self.activation_generation = 0
        self.preview_running = False
        self.preview_pending = None
        self.query = ft.TextField(label='検索文字列', hint_text='空白区切り（例：A B）でAND検索。ファイル名内のA・Bの出現順に関係なく検索されます。空白を含む文字列は " " で囲みます（例："A B"）。',
                                  expand=True, on_submit=self.search, on_focus=self.caret_end)
        self.search_button = ft.Button('検索', on_click=self.search, style=button_style)
        self.query.tooltip = self.query.hint_text
        self.search_indicator = ft.ProgressBar(width=160, height=6, value=None, visible=False)
        self.search_controls = ft.Row([self.search_button, self.search_indicator, self.query], expand=True, spacing=8)
        self.result_count = ft.Text('検索結果：0件', weight=ft.FontWeight.BOLD)
        self.stack_count = ft.Text('', weight=ft.FontWeight.BOLD)
        self.export_button = ft.Button('PDF出力', on_click=self.export, style=button_style)
        self.open_button = ft.Button('PDFを開く', on_click=self.open_selected, style=button_style)
        self.result_table = self.new_table()
        self.stack_table = self.new_table()
        self.result_section = ft.Column([
            ft.Row([self.result_count, ft.Container(expand=True), ft.TextButton('全選択', on_click=self.select_all),
                    ft.TextButton('全解除', on_click=self.deselect_all),
                    ft.Button('ストックへ追加', on_click=self.add_selected, style=button_style)]),
            ft.Container(content=self.result_table, expand=True),
        ], expand=True, spacing=4)
        self.stack_section = ft.Container(content=ft.Column([
            ft.Row([self.stack_count, ft.Container(expand=True), ft.TextButton('全選択', on_click=self.check_all),
                    ft.TextButton('全解除', on_click=self.uncheck_all),
                    ft.TextButton('全削除', on_click=self.confirm_clear), self.open_button, self.export_button]),
            ft.Container(content=self.stack_table, expand=True),
        ], expand=True, spacing=4), bgcolor='#303438', padding=6, expand=True)
        self.wide = False
        self.result_tab = ft.Tab(label='検索結果')
        self.stack_tab = ft.Tab(label='ストック')
        self.tabs = ft.Tabs(length=2, selected_index=0, expand=True,
            on_change=self.on_tab_change,
            content=ft.Column([
                ft.TabBar(tabs=[self.result_tab, self.stack_tab]),
                ft.TabBarView(controls=[
                    ft.Container(content=self.result_section, padding=6), self.stack_section,
                ], expand=True),
            ], expand=True, spacing=4))
        self.lists = ft.Container(content=self.tabs, expand=True)
        self.image = ft.Image(src='', fit=ft.BoxFit.CONTAIN, expand=True, visible=False)
        self.preview_label = ft.Text('', size=14, color=ft.Colors.BLUE_100,
                                     weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER)
        self.preview_panel = ft.Container(content=ft.Column([self.preview_label, self.image],
            expand=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=2, expand=True, visible=False)
        self.body = ft.Row([self.lists, self.preview_panel], expand=True,
                           vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        self.view = ft.Container(content=self.body, expand=True, visible=False)
        self.render()

    @staticmethod
    def new_table():
        return dt2.DataTable2(columns=[ft.DataColumn(ft.Text('PDF'))], rows=[],
                              fixed_top_rows=1, data_row_height=72, heading_row_height=48,
                              heading_row_color=ft.Colors.BLUE_GREY_900,
                              column_spacing=8, horizontal_margin=8, min_width=620,
                              visible_horizontal_scroll_bar=True, visible_vertical_scroll_bar=True)

    def caret_end(self, event=None):
        offset = len((self.query.value or '').encode('utf-16-le')) // 2
        self.query.selection = ft.TextSelection(base_offset=offset, extent_offset=offset)
        self.page.update()

    async def focus(self):
        if self.view.visible and not self.busy():
            await self.query.focus()
            self.caret_end()

    def clear_preview(self):
        self.preview_generation += 1
        self.preview_pending = None
        self.image.visible = False
        self.preview_label.value = ''

    def on_tab_change(self, event=None):
        self.clear_preview()
        self.page.update()

    def activate(self, active):
        self.activation_generation += 1
        self.view.visible = active
        self.preview_generation += 1
        self.preview_pending = None
        if active:
            self.resize()
            self.message.value = self.load_error or f'検索結果：{len(self.results)}件。'
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
        wide = (self.page.width or 1200) >= 1700
        changed = wide != self.wide
        self.wide = wide
        self.preview_panel.visible = wide
        self.lists.expand = not wide
        # Preserve the old path width independently of the narrower table.
        previous_width = max(1200, (self.page.width or 1200) - 400)
        path_width = min(600, max(450, previous_width - 900))
        previous_filename = max(360, previous_width - path_width - 46 - 96 - 100 - 16)
        self.lists.width = previous_width - previous_filename / 2 if wide else None
        self.image.height = max(100, (self.page.height or 800) - 300)
        if changed:
            self.clear_preview()
        self.render()

    def report_error(self, exc):
        self.message.value = str(exc)
        self.page.update()

    async def search(self, event=None):
        if self.busy():
            return
        try:
            words = parse_search_query(self.query.value)
        except ValueError as exc:
            self.report_error(exc)
            await self.focus()
            return
        if not words:
            self.report_error('検索文字列を入力してください。')
            await self.focus()
            return
        folder = self.folder().strip()
        self.search_indicator.value = None
        self.search_indicator.visible = True
        self.set_busy(True, 'PDF一覧を取得中：0件')
        self.activation_generation += 1
        self.preview_generation += 1
        self.preview_pending = None
        try:
            def work(report):
                if not folder or not Path(folder).is_dir():
                    raise ValueError('有効な検索先フォルダを指定してください。')
                cached = self.collect(folder, lambda count: report((f'PDF一覧を取得中：{count}件', None)))
                results = search_files(words, cached, lambda current, total: report((
                    f'ファイル名を検索中：{current}/{total}件', current / total if total else 1.0)))
                return cached, results
            files, results = await self.worker(work)
            self.files, self.index_folder = files, path_key(folder)
            self.results, self.selection = results, set()
            self.metadata.update({path_key(item['path']): item for item in results})
            self.image.visible = False
            self.preview_label.value = ''
            self.tabs.selected_index = 0
            self.message.value = f'検索結果：{len(results)}件。'
        except Exception as exc:
            self.message.value = f'検索できませんでした：{exc}'
        finally:
            self.search_indicator.visible = False
            self.set_busy(False)
            self.render()
            self.page.update()
            await self.focus()

    @staticmethod
    def header(label, count=None, color=ft.Colors.GREEN_100):
        title = ft.Text(label, size=12, weight=ft.FontWeight.BOLD)
        if count is None:
            return title
        return ft.Row([title, ft.Container(ft.Text(str(count), size=12,
            color=ft.Colors.BLACK, weight=ft.FontWeight.BOLD),
            padding=ft.Padding.symmetric(horizontal=7, vertical=3), border_radius=12,
            bgcolor=color)], spacing=4, alignment=ft.MainAxisAlignment.CENTER)

    def folder_label(self, path):
        try:
            relative = os.path.relpath(str(Path(path).parent), self.folder().strip())
            return '（検索先直下）' if relative == '.' else relative
        except (ValueError, OSError):
            return str(Path(path).parent)

    def render(self):
        stacked = {path_key(item['path']) for item in self.items}
        self.selection.difference_update(stacked)
        output_count = sum(i['selected'] for i in self.items)
        self.result_count.value = f'検索結果：{len(self.results)}件'
        self.stack_count.value = f'ストック：{len(self.items)}件'
        self.result_tab.label = self.header('検索結果', len(self.results), ft.Colors.BLUE_100)
        self.stack_tab.label = self.header('ストック', len(self.items), ft.Colors.BLUE_100)
        self.export_button.disabled = self.busy() or not output_count or bool(self.load_error)
        self.open_button.disabled = self.export_button.disabled
        available_width = (max(1200, (self.page.width or 1200) - 400) if self.wide
                           else max(600, (self.page.width or 1200) - 60))
        path_width = min(600, max(450, available_width - 900))
        for table, items, is_stack in ((self.result_table, self.results, False), (self.stack_table, self.items, True)):
            columns = [('項番', 46), ('パス', path_width), ('ファイル名', None), ('更新日時', 96)]
            if not self.wide:
                columns.append(('プレビュー', 80))
            if is_stack:
                columns.append(('削除', 64))
            columns.append(('選択' if is_stack else '追加', 100))
            table.min_width = sum(width or (180 if self.wide else 360) for _, width in columns) + 16
            table.columns = [dt2.DataColumn2(self.header(label,
                (output_count if is_stack else len(self.selection)) if index == len(columns)-1 else None,
                ft.Colors.GREEN_100 if is_stack else ft.Colors.BLUE_100), fixed_width=width)
                for index, (label, width) in enumerate(columns)]
            rows = []
            for number, item in enumerate(items, 1):
                path = item['path']
                key = path_key(path)
                meta = self.metadata.get(key, item)
                async def change(e, key=key, is_stack=is_stack):
                    if self.busy():
                        return
                    if is_stack:
                        await self.commit([dict(i, selected=bool(e.control.value)) if path_key(i['path']) == key else dict(i) for i in self.items])
                    else:
                        self.selection.add(key) if e.control.value else self.selection.discard(key)
                        self.render()
                        self.page.update()
                checkbox = ft.Checkbox(value=item['selected'] if is_stack else key in self.selection,
                    disabled=bool(self.load_error) or (not is_stack and key in stacked), on_change=change)
                async def open_file(e, path=path):
                    self.caret_end()
                    await self.open_pdf(path, False)
                async def open_folder(e, path=path):
                    self.caret_end()
                    await self.open_pdf(path, True)
                def preview(e, path=path):
                    self.show_preview_dialog(path)
                async def remove(e, key=key):
                    await self.commit([dict(i) for i in self.items if path_key(i['path']) != key])
                def hover(e, path=path):
                    if not self.wide:
                        return
                    if e.data is True or e.data == 'true':
                        self.request_preview(path)
                    else:
                        self.clear_preview()
                        self.page.update()
                label = Path(path).name
                status = '（追加済み）' if not is_stack and key in stacked else ''
                if meta.get('available') is False:
                    status += '（参照不可）'
                def link(value, click, color, tooltip, lines=1):
                    return ft.Container(ft.Text(value, size=14, color=color,
                        no_wrap=lines == 1, max_lines=lines, overflow=ft.TextOverflow.ELLIPSIS),
                        on_click=click, on_hover=hover, ink=True, tooltip=tooltip,
                        alignment=ft.Alignment.CENTER_LEFT)
                folder = self.folder_label(path)
                modified = meta.get('modified')
                date = datetime.fromtimestamp(modified).strftime('%Y/%m/%d\n%H:%M') if modified is not None else '—'
                def centered(control):
                    return ft.DataCell(ft.Container(control, alignment=ft.Alignment.CENTER))
                cells = [centered(ft.Text(str(number), size=14)),
                    ft.DataCell(link(folder, open_folder, ft.Colors.WHITE, str(Path(path).parent))),
                    ft.DataCell(link(label + status, open_file, ft.Colors.BLUE_200, path + status, lines=2)),
                    ft.DataCell(ft.Text(date, size=14, no_wrap=True, max_lines=2))]
                if not self.wide:
                    cells.append(centered(ft.IconButton(icon=ft.Icons.VISIBILITY_OUTLINED,
                        tooltip='PDFをプレビュー', on_click=preview)))
                if is_stack:
                    cells.append(centered(ft.IconButton(icon=ft.Icons.DELETE_OUTLINE,
                        icon_color=ft.Colors.ORANGE_300, tooltip='ストックから削除',
                        on_click=remove, disabled=bool(self.load_error))))
                cells.append(centered(checkbox))
                rows.append(ft.DataRow(cells=cells))
            table.rows = rows

    def show_preview_dialog(self, path):
        if self.busy():
            return
        self.caret_end()
        picture = ft.Image(src='', width=760, height=520, fit=ft.BoxFit.CONTAIN, visible=False)
        label = ft.Text('プレビューを読み込んでいます…', size=14)
        state = {'open': True, 'generation': 0}
        async def load(event=None):
            state['generation'] += 1
            generation = state['generation']
            picture.visible = False
            self.page.update()
            try:
                source = await asyncio.to_thread(self.make_preview, path)
                if not state['open'] or generation != state['generation']:
                    return
                picture.src, picture.visible = source, True
                label.value = self.folder_label(path) + ' / ' + Path(path).name
            except Exception as exc:
                if state['open'] and generation == state['generation']:
                    label.value = f'プレビューできません：{exc}'
            self.page.update()
        def close(event=None):
            state['open'] = False
            self.page.pop_dialog()
            self.caret_end()
        dialog = ft.AlertDialog(modal=True, title=ft.Text('PDFプレビュー'),
            content=ft.Container(width=860, height=min(640, max(260, (self.page.height or 800)-180)),
                content=ft.Column([label, ft.Container(picture, expand=True,
                    alignment=ft.Alignment.CENTER, border=ft.Border.all(1, ft.Colors.GREY_500),
                    border_radius=8, padding=10, bgcolor=ft.Colors.GREY_200)], expand=True)),
            actions=[ft.TextButton('再読み込み', on_click=load), ft.TextButton('閉じる', on_click=close)])
        self.page.show_dialog(dialog)
        self.page.run_task(load)

    async def commit(self, items):
        if self.busy() or self.load_error:
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
        if await self.commit(add_to_stack(self.items, paths)):
            self.selection.clear()
        self.render()
        self.page.update()

    def select_all(self, e=None):
        if self.busy():
            return
        stacked = {path_key(i['path']) for i in self.items}
        self.selection = {path_key(i['path']) for i in self.results} - stacked
        self.render()
        self.page.update()

    def deselect_all(self, e=None):
        if not self.busy():
            self.selection.clear()
            self.render()
            self.page.update()

    async def check_all(self, e=None):
        await self.commit([dict(i, selected=True) for i in self.items])

    async def uncheck_all(self, e=None):
        await self.commit([dict(i, selected=False) for i in self.items])

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
        if self.busy() or not self.view.visible:
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
        if self.busy() or self.load_error:
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
        if self.busy() or self.load_error:
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

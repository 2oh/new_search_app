"""Sheet results and persistent worksheet selection within composite mode."""
from datetime import datetime
from pathlib import Path

import flet as ft

import sheet_stock as stock
from sheet_export import export_sheets


class SheetStockView:
    def __init__(self, owner, path, *, button_style, selection_style):
        self.owner, self.page = owner, owner.page
        self.path = Path(path)
        self.results, self.items, self.checked, self.boxes = [], [], set(), {}
        self.in_stock = False
        self.load_error = ''
        try:
            self.items = stock.load(self.path)
        except (OSError, ValueError) as exc:
            self.load_error = f'シートストックを読み込めません。保存データを保持します：{exc}'
        self.results_tab = ft.Tab(label='シート一覧')
        self.stock_tab = ft.Tab(label='シートストック')
        self.count = ft.Text()
        self.add_button = ft.Button('シートをストックへ追加', on_click=self.add, style=button_style)
        self.export_button = ft.Button('シートをExcel出力', on_click=self.export, style=button_style)
        self.remove_button = ft.TextButton('選択シートを削除', on_click=self.confirm_remove)
        self.toolbar = ft.Row([self.count, ft.Container(expand=True),
            ft.Button('全選択', on_click=lambda e: self.select_all(True), style=selection_style),
            ft.Button('全解除', on_click=lambda e: self.select_all(False), style=selection_style),
            self.add_button, self.remove_button, self.export_button], spacing=8)
        self.heading = ft.Container(height=36, padding=6, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST)
        self.list = ft.ListView(expand=True, spacing=0, build_controls_on_demand=True)
        self.view = ft.Column([self.toolbar, self.heading, self.list], expand=True, spacing=4, visible=False,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self.update_tabs()

    def update_tabs(self):
        self.results_tab.label = f'シート一覧（{len(self.results)}）'
        self.stock_tab.label = f'シートストック（{len(self.items)}）'

    def open(self, in_stock):
        self.in_stock = in_stock
        self.view.visible = True
        self.render()
        if self.load_error:
            self.owner.message(self.load_error)

    def replace_results(self, rows):
        self.results, self.checked = rows, set()
        self.update_tabs()
        if self.view.visible:
            self.render()

    def rows(self):
        return self.items if self.in_stock else self.results

    @staticmethod
    def columns(controls):
        return ft.Row([ft.Container(control, width=width, expand=expand) for control, width, expand in
            zip(controls, (44, None, None, 154, 110, 60, 70), (None, 3, 3, None, None, None, None))], spacing=8)

    def render(self):
        self.update_tabs()
        self.add_button.visible = not self.in_stock
        self.remove_button.visible = self.export_button.visible = self.in_stock
        headings = ('項番', 'フォルダ', 'Excel名', 'シート名', '更新日時', '選択',
                    '並べ替え' if self.in_stock else '一致明細')
        self.heading.content = self.columns([ft.Text(title, size=13) for title in headings])
        stored = {stock.sheet_key(item): item for item in self.items}
        self.boxes = {}
        self.list.controls = [self.make_row(number, item, stored) for number, item in enumerate(self.rows(), 1)]
        self.update_selection()

    def make_row(self, number, item, stored):
        key = stock.sheet_key(item)
        saved = stored.get(key)
        already_added = not self.in_stock and saved is not None and stock.same_source_version(saved, item)
        path = stock.source_path(item)

        def change(event):
            if self.owner.normal.busy() or self.load_error:
                return
            if self.in_stock:
                self.save([dict(row, selected=event.control.value) if stock.sheet_key(row) == key else row
                           for row in self.items], rebuild=False)
            else:
                self.checked.add(key) if event.control.value else self.checked.discard(key)
                self.update_selection()
                self.page.update()

        async def launch(event):
            await self.owner.open_occurrence(dict(path=str(path), sheet=item['sheet']))

        checkbox = ft.Checkbox(disabled=already_added or bool(self.load_error), on_change=change)
        self.boxes[key] = checkbox
        check = checkbox
        if saved is not None and not self.in_stock:
            check = ft.Column([checkbox, ft.Text('ストック済' if already_added else '要更新', size=11)],
                spacing=0, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        suffix = ft.Text(f"{item.get('hits', 0)}件", size=13)
        if self.in_stock:
            suffix = ft.Row([ft.IconButton(ft.Icons.ARROW_UPWARD, width=32, icon_size=16,
                disabled=number == 1, tooltip='上へ', on_click=lambda e: self.move(key, -1)),
                ft.IconButton(ft.Icons.ARROW_DOWNWARD, width=32, icon_size=16,
                    disabled=number == len(self.items), tooltip='下へ', on_click=lambda e: self.move(key, 1))], spacing=0)
        updated = datetime.fromtimestamp(item['mtime'] / 1_000_000_000).strftime('%Y/%m/%d %H:%M')
        relative = str(Path(item['path']).parent)
        return ft.Container(self.columns([ft.Text(str(number)),
            ft.Text(relative if relative != '.' else '（直下）', max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                    tooltip=str(path.parent)),
            ft.Text(path.name, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, tooltip=str(path)),
            ft.TextButton(ft.Text(item['sheet'], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                          on_click=launch, tooltip=f'{path}\n{item["sheet"]}'),
            ft.Text(updated, size=12), check, suffix]), padding=6,
            border=ft.Border(bottom=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)))

    def update_selection(self):
        keys = ({stock.sheet_key(item) for item in self.items if item['selected']} if self.in_stock else self.checked)
        for key, checkbox in self.boxes.items():
            checkbox.value = key in keys
        self.count.value = f'{len(self.rows())}シート / 選択 {len(keys)}シート'
        self.add_button.disabled = self.export_button.disabled = self.remove_button.disabled = not keys or bool(self.load_error)

    def select_all(self, value):
        if self.owner.normal.busy() or self.load_error:
            return
        if self.in_stock:
            self.save([dict(item, selected=value) for item in self.items], rebuild=False)
        else:
            self.checked = {key for key, box in self.boxes.items() if value and not box.disabled}
            self.update_selection()
            self.page.update()

    def save(self, items, *, rebuild=True):
        if self.owner.normal.busy() or self.load_error:
            return False
        try:
            stock.save(self.path, items)
        except (OSError, ValueError) as exc:
            self.update_selection()
            self.owner.message(f'シートストックを保存できません：{exc}')
            return False
        self.items = items
        if rebuild:
            self.render()
        else:
            self.update_selection()
        self.page.update()
        return True

    def add(self, event=None):
        rows = [row for row in self.results if stock.sheet_key(row) in self.checked]
        if not rows:
            return
        previous = self.checked.copy()
        self.checked.clear()
        if self.save(stock.add(self.items, rows)):
            self.owner.message(f'{len(rows)}シートを保存しました（シートストック {len(self.items)}件）')
        else:
            self.checked = previous
            self.update_selection()
            self.page.update()

    def move(self, key, offset):
        items = self.items.copy()
        index = next((index for index, item in enumerate(items) if stock.sheet_key(item) == key), None)
        if index is not None and 0 <= index + offset < len(items):
            items[index], items[index + offset] = items[index + offset], items[index]
            self.save(items)

    def confirm_remove(self, event=None):
        if self.owner.normal.busy() or self.load_error:
            return

        def remove(event):
            self.page.pop_dialog()
            self.save([item for item in self.items if not item['selected']])

        self.page.show_dialog(ft.AlertDialog(title=ft.Text('選択シートをストックから削除しますか？'),
            actions=[ft.TextButton('キャンセル', on_click=lambda e: self.page.pop_dialog()),
                     ft.Button('削除', on_click=remove)]))

    async def export(self, event=None):
        normal = self.owner.normal
        if normal.busy() or self.load_error:
            return
        if not any(item['selected'] for item in self.items):
            self.owner.message('出力するシートを選択してください')
            return
        folder = (normal.output_folder() or '').strip()
        if not folder or not Path(folder).is_dir():
            self.owner.message('出力先フォルダを指定してください（上段のPDF出力先フォルダを共用します）')
            return
        normal.set_busy(True, 'Excelを起動してシートを結合しています…')
        self.owner.progress.visible = True
        self.owner.progress.value = None
        self.page.update()
        try:
            output = await self.owner.run_search_worker(lambda report: export_sheets(
                self.items, folder, lambda message: report((message, None)),
                log_path=self.path.with_name('sheet_export.log')))
            self.owner.message(f'シートをExcelに出力しました：{output}')
        except Exception as exc:
            self.owner.message(f'シートをExcelに出力できません：{exc}')
        finally:
            self.owner.progress.visible = False
            normal.set_busy(False)
            self.page.update()

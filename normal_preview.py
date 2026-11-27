"""Keyboard and list state for the PDF filename mode's preview pane."""
from datetime import datetime
import inspect
from pathlib import Path

import flet as ft
from normal_search import path_key
from preview_keys import VERTICAL_KEYS, VerticalKeyRepeat


ROW_HEIGHT = 52
SHOW_PREVIEW = 'PDFプレビューを表示'
HIDE_PREVIEW = 'PDFプレビューを閉じる'


class NormalPreview:
    def init_preview(self):
        self.on_preview_visibility = None
        self.preview_index = None
        self.preview_stock = False
        self.preview_rows = []
        self.preview_checks = {}
        self.preview_paths = []
        self.preview_path_cells = []
        self.preview_offset = 0
        self.preview_viewport = None
        self.preview_focused = False
        self.key_repeat = VerticalKeyRepeat(self.page, self.can_navigate, self.move_preview)
        self.preview_target = ft.TextField(width=1, height=1, read_only=True,
            ignore_up_down_keys=True, opacity=0, visible=False, border=ft.InputBorder.NONE,
            enable_interactive_selection=False, content_padding=0,
            on_focus=lambda e: setattr(self, 'preview_focused', True),
            on_blur=lambda e: setattr(self, 'preview_focused', False))
        self.preview_button = ft.OutlinedButton(SHOW_PREVIEW, on_click=self.toggle_preview)
        self.preview_hint = ft.Text('↑↓ PDFを移動 ｜ Enter チェックを切り替え ｜ Esc 閉じる', size=12, visible=False)
        self.preview_list = ft.ListView(expand=True, spacing=0, padding=0, item_extent=ROW_HEIGHT,
            build_controls_on_demand=True, on_scroll=self.track_preview_scroll)
        self.preview_heading = ft.Row(spacing=8)
        self.preview_listing = ft.Column([ft.Container(self.preview_heading, height=36,
            padding=ft.Padding.symmetric(horizontal=6), bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST),
            self.preview_list], spacing=0, visible=False)
        previous = self.page.on_keyboard_event

        async def route(event):
            if not self.can_navigate():
                if previous:
                    result = previous(event)
                    if inspect.isawaitable(result):
                        await result
                return
            key = event.key.replace(' ', '')
            if key in VERTICAL_KEYS:
                if not self.preview_focused:
                    await self.focus_preview()
                self.key_repeat.start(event)
                await self.move_preview(event)
            elif key in ('Enter', 'NumpadEnter') and self.preview_focused and self.preview_index is not None:
                self.key_repeat.stop()
                await self.toggle_preview_check(self.preview_index)
            elif key == 'Escape':
                await self.toggle_preview()

        self.page.on_keyboard_event = route

    async def move_preview(self, event):
        delta = -1 if event.key.replace(' ', '') == 'ArrowUp' else 1
        index = 0 if self.preview_index is None else self.preview_index + delta
        await self.preview_at(index, scroll=True)

    def can_navigate(self):
        return self.view.visible and self.preview_panel.visible and not self.busy()

    async def focus_preview(self):
        if self.can_navigate():
            await self.preview_target.focus()

    def track_preview_scroll(self, event):
        self.preview_offset, self.preview_viewport = event.pixels, event.viewport_dimension

    def set_preview_layout(self):
        width = self.page.width or 1200
        old_panel = max(350, width * .40)
        old_path = min(self.table_path_width() * .75, width * .25)
        # Other columns, margins and gaps keep their original widths.
        old_name = max(0, width - old_panel - old_path - 263)
        self.preview_panel.width = old_panel + (old_path + old_name) * .10
        path_width = old_path * .90
        for cell in self.preview_path_cells:
            cell.width = path_width

    def build_preview_rows(self, items):
        self.preview_rows, self.preview_paths = [], []
        self.preview_path_cells, self.preview_checks = [], {}

        def columns(number, folder, name, date, check):
            path_cell = ft.Container(folder)
            self.preview_path_cells.append(path_cell)
            return [ft.Container(number, width=40), path_cell, ft.Container(name, expand=True),
                    ft.Container(date, width=85), ft.Container(check, width=66)]

        self.preview_heading.controls = columns(
            ft.Text('項番'), ft.Text('パス'), ft.Text('ファイル名'), ft.Text('更新日時'),
            ft.Text('選択' if self.preview_stock else '追加'))
        boxes = self.selection_boxes[self.preview_stock]
        stacked = {path_key(item['path']) for item in self.items}
        for index, item in enumerate(items):
            path = item['path']
            self.preview_paths.append(path)
            key = path_key(path)
            original = boxes[key]
            meta = self.metadata.get(key, item)
            stamp = meta.get('modified')
            date = datetime.fromtimestamp(stamp).strftime('%Y/%m/%d\n%H:%M') if stamp is not None else '—'
            status = '（参照不可）' if meta.get('available') is False else ''

            async def select(event, index=index):
                if self.can_navigate():
                    await self.focus_preview()
                    await self.preview_at(index)

            async def change(event, key=key):
                if self.can_navigate():
                    await self.set_row_check(self.preview_stock, key, bool(event.control.value))
                    await self.focus_preview()

            checkbox = ft.Checkbox(value=original.value, disabled=original.disabled,
                                   tooltip=original.tooltip, on_change=change)
            self.preview_checks[key] = checkbox
            check = self.stocked_checkbox(checkbox) if not self.preview_stock and key in stacked else checkbox
            self.preview_rows.append(ft.Container(ft.Row(columns(
                ft.Text(str(index + 1)), ft.Text(self.folder_label(path), max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS, tooltip=str(Path(path).parent)),
                ft.Text(Path(path).name + status, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                        tooltip=path + status),
                ft.Text(date, size=13), check), spacing=8), on_click=select, height=ROW_HEIGHT,
                padding=ft.Padding.symmetric(horizontal=6),
                border=ft.Border(bottom=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT))))
        self.preview_list.controls = self.preview_rows
        self.set_preview_layout()

    async def toggle_preview(self, event=None):
        if self.busy() or self.pending_selection:
            return
        if self.preview_panel.visible:
            self.close_preview()
            self.page.update()
            return
        self.preview_stock = self.tabs.selected_index == 1
        items = self.items if self.preview_stock else self.results
        if not items:
            self.report_error('プレビューするPDFがありません')
            return
        self.build_preview_rows(items)
        self.preview_panel.visible = self.preview_hint.visible = True
        self.preview_target.visible = True
        self.preview_button.content = HIDE_PREVIEW
        self.tab_bar.disabled = self.result_actions.disabled = self.stock_actions.disabled = True
        self.folder_button.disabled = True
        self.update_tab_actions()
        self.tab_content.visible = False
        self.preview_listing.visible = True
        if self.on_preview_visibility:
            self.on_preview_visibility(True)
        await self.preview_at(0)
        await self.focus_preview()

    def close_preview(self):
        if not self.preview_panel.visible:
            return
        self.key_repeat.stop()
        self.preview_panel.visible = self.preview_hint.visible = False
        self.preview_target.visible = self.preview_focused = False
        self.preview_button.content = SHOW_PREVIEW
        self.tab_bar.disabled = self.result_actions.disabled = self.stock_actions.disabled = False
        self.folder_button.disabled = self.match_count == 0
        self.update_tab_actions()
        self.tab_content.visible = True
        self.preview_listing.visible = False
        self.preview_index = None
        self.preview_offset, self.preview_viewport = 0, None
        self.preview_rows, self.preview_paths, self.preview_path_cells, self.preview_checks = [], [], [], {}
        self.preview_list.controls = []
        self.clear_preview()
        if self.on_preview_visibility:
            self.on_preview_visibility(False)

    async def preview_at(self, index, *, scroll=False):
        if not self.can_navigate() or not self.preview_rows:
            return
        index = max(0, min(len(self.preview_rows) - 1, index))
        if index == self.preview_index:
            return
        if self.preview_index is not None:
            self.preview_rows[self.preview_index].bgcolor = None
        self.preview_index = index
        self.preview_rows[index].bgcolor = ft.Colors.SECONDARY_CONTAINER
        self.request_preview(self.preview_paths[index])
        if scroll:
            top = index * ROW_HEIGHT
            viewport = self.preview_viewport or max(ROW_HEIGHT, (self.page.height or 800) - 330)
            offset = max(0, min(top, max(self.preview_offset, top + ROW_HEIGHT - viewport)))
            if offset != self.preview_offset:
                self.preview_offset = offset
                await self.preview_list.scroll_to(offset=offset)

    async def toggle_preview_check(self, index):
        key = path_key(self.preview_paths[index])
        checkbox = self.preview_checks[key]
        if not checkbox.disabled and not self.pending_selection:
            await self.set_row_check(self.preview_stock, key, not checkbox.value)

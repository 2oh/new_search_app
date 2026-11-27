"""Read-only preview of adopted drawings in the source workbook's row order."""
import asyncio
import inspect
from pathlib import Path

import flet as ft
import pandas as pd


ROW_HEIGHT = 58
HEADINGS = ('項番', '材料', '品番/PG名', '抽出対象', '出力PDF')


def text_value(value):
    return '' if pd.isna(value) else str(value).strip()


class BomPreview:
    def __init__(self, page, *, busy, make_preview, split_path, open_pdf):
        self.page, self.busy = page, busy
        self.make_preview, self.split_path, self.open_pdf = make_preview, split_path, open_pdf
        self.on_visibility = None
        self.index = None
        self.paths = []
        self.generation = 0
        self.pending = None
        self.loading = False
        self.opening_pdf = False
        self.navigation_focused = False
        self.offset = 0
        self.viewport = None
        self.button = ft.OutlinedButton('PDFプレビューを表示')
        self.hint = ft.Text('↑↓ 行を移動 ｜ Enter PDFを開く ｜ Esc 閉じる', size=12, visible=False)
        self.key_target = ft.TextField(width=1, height=1, read_only=True, opacity=0, visible=False,
            ignore_up_down_keys=True, enable_interactive_selection=False,
            border=ft.InputBorder.NONE, content_padding=0,
            on_focus=lambda e: setattr(self, 'navigation_focused', True),
            on_blur=lambda e: setattr(self, 'navigation_focused', False))
        self.heading = ft.Container(self.columns([ft.Text(name, size=13) for name in HEADINGS]),
            padding=6, height=36, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST)
        self.list = ft.ListView(expand=True, padding=0, spacing=0, item_extent=ROW_HEIGHT,
            build_controls_on_demand=True, on_scroll=self.track_scroll)
        self.listing = ft.Column([self.heading, self.list], spacing=0, visible=False)
        self.label = ft.Text(size=14, color=ft.Colors.PRIMARY, weight=ft.FontWeight.BOLD,
            max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)
        self.open_button = ft.TextButton('PDFを開く', on_click=self.launch, visible=False)
        self.image = ft.Image(src='', fit=ft.BoxFit.CONTAIN, expand=True, visible=False)
        self.panel = ft.Container(ft.Column([ft.Row([ft.Container(self.label, expand=True), self.open_button]),
            self.image], expand=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=8, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST, visible=False)

    @staticmethod
    def columns(controls):
        return ft.Row([ft.Container(control, width=width, expand=2 if width is None else None)
            for control, width in zip(controls, (42, 104, None, 70, None))], spacing=8)

    def bind_keyboard(self):
        previous = self.page.on_keyboard_event

        async def route(event):
            if not self.can_navigate():
                if previous:
                    result = previous(event)
                    if inspect.isawaitable(result):
                        await result
                return
            key = event.key.replace(' ', '')
            if key == 'Escape':
                self.close()
                self.page.update()
            elif key in ('ArrowUp', 'ArrowDown'):
                delta = -1 if key == 'ArrowUp' else 1
                await self.select((self.index if self.index is not None else 0) + delta, scroll=True)
                if not self.navigation_focused:
                    await self.focus()
            elif key in ('Enter', 'NumpadEnter') and self.navigation_focused:
                await self.launch(event)
        self.page.on_keyboard_event = route

    def can_navigate(self):
        return self.panel.visible and not self.busy()

    async def focus(self):
        if self.can_navigate():
            await self.key_target.focus()

    def resize(self):
        self.panel.width = max(420, (self.page.width or 1200) * .46)

    def track_scroll(self, event):
        self.offset, self.viewport = event.pixels, event.viewport_dimension

    async def toggle(self, df):
        if self.busy() or df.empty:
            return
        if self.panel.visible:
            self.close()
            self.page.update()
            return
        rows = []

        def lines(value, *, color=None, max_lines=2):
            return ft.Text(value, size=14, max_lines=max_lines, no_wrap=max_lines == 1, color=color,
                overflow=ft.TextOverflow.ELLIPSIS, tooltip=value or None)

        for index, (_, row) in enumerate(df.iterrows()):
            eligibility = text_value(row.get('出力可否', ''))
            path = text_value(row.get('採用PDFパス', '')) if eligibility != '不可' else ''
            self.paths.append(path)
            identity = '\n'.join(filter(None, (text_value(row.get('品番', '')), text_value(row.get('PG名', '')))))
            if path:
                folder, filename = self.split_path(path)
                pdf = ft.Column([lines(folder or str(Path(path).parent), max_lines=1),
                                 lines(filename, color=ft.Colors.PRIMARY, max_lines=1)],
                    spacing=0, tight=True)
            else:
                pdf = lines(text_value(row.get('候補状態', '')) if eligibility != '不可' else '')

            async def click(event, index=index):
                await self.select(index)
                await self.focus()

            status = '対象' if eligibility == '可' else eligibility
            status_color = {'可': ft.Colors.GREEN_700, '不可': ft.Colors.RED_700}.get(eligibility)
            rows.append(ft.Container(self.columns([lines(str(index + 1)),
                lines(text_value(row.get('材料', ''))), lines(identity), lines(status, color=status_color), pdf]),
                padding=6, height=ROW_HEIGHT, on_click=click,
                border=ft.Border(bottom=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT))))
        self.list.controls = rows
        self.resize()
        self.set_visible(True)
        first = next((index for index, path in enumerate(self.paths) if path), 0)
        await self.select(first, scroll=True)
        await self.focus()

    def set_visible(self, visible):
        self.panel.visible = self.listing.visible = self.hint.visible = self.key_target.visible = visible
        self.button.content = 'PDFプレビューを閉じる' if visible else 'PDFプレビューを表示'
        if self.on_visibility:
            self.on_visibility(visible)

    def close(self):
        if not self.panel.visible:
            return
        self.generation += 1
        self.pending = None
        self.index = None
        self.navigation_focused = False
        self.paths = []
        self.offset, self.viewport = 0, None
        self.list.controls = []
        self.image.visible = self.open_button.visible = False
        self.set_visible(False)

    async def select(self, index, *, scroll=False):
        if not self.can_navigate() or not self.paths:
            return
        index = max(0, min(len(self.paths) - 1, index))
        if self.index == index:
            return
        if self.index is not None:
            self.list.controls[self.index].bgcolor = None
        self.index = index
        self.list.controls[index].bgcolor = ft.Colors.SECONDARY_CONTAINER
        path = self.paths[index]
        self.generation += 1
        self.pending = (self.generation, path) if path else None
        self.image.visible = False
        self.open_button.visible = bool(path)
        self.label.value = f'読込中：{Path(path).name}' if path else 'この行に出力PDFはありません'
        self.page.update()
        if path and not self.loading:
            self.page.run_task(self.load)
        if scroll:
            top = index * ROW_HEIGHT
            viewport = self.viewport or max(ROW_HEIGHT, (self.page.height or 800) - 350)
            offset = max(0, min(top, max(self.offset, top + ROW_HEIGHT - viewport)))
            if offset != self.offset:
                self.offset = offset
                await self.list.scroll_to(offset=offset)

    async def load(self):
        if self.loading:
            return
        self.loading = True
        try:
            while self.pending:
                generation, path = self.pending
                self.pending = None
                try:
                    image = await asyncio.to_thread(self.make_preview, path)
                except Exception as exc:
                    if generation == self.generation:
                        self.label.value = f'プレビューできません：{exc}'
                        self.page.update()
                else:
                    if generation == self.generation:
                        self.image.src, self.image.visible = image, True
                        self.label.value = Path(path).name
                        self.page.update()
        finally:
            self.loading = False

    async def launch(self, event):
        if self.can_navigate() and self.index is not None and not self.opening_pdf:
            path = self.paths[self.index]
            if path:
                self.opening_pdf = True
                try:
                    await self.open_pdf(path, False)
                finally:
                    self.opening_pdf = False
                    await self.focus()

"""Reusable result rows and list-local keyboard navigation for composite search."""
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
import asyncio
import inspect
import sys
import flet as ft


class CompositeRows:
    def init_rows(self):
        self.row_cache = {}
        self.active_key = None
        self.expanded_keys = set()
        self.scroll_offset = 0
        self.viewport_height = 400
        self.list.on_scroll = self.on_list_scroll
        self.heading_assy = ft.Container(ft.Text('使用ASSY', weight=ft.FontWeight.BOLD), width=440)
        self.heading = ft.Row([self.core_columns([
            ft.Text('品番／PG'), ft.Text('代表品名'), ft.Text('材料'), ft.Text('PDF'), ft.Text('選択')]),
            self.heading_assy], spacing=8)
        self.heading_box = ft.Container(self.heading, padding=6, height=36,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST)
        self.list_panel = ft.Column([self.heading_box, self.list], expand=True, spacing=0,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        # Consume Flutter's default directional focus/scroll action locally.
        # Preview locks the search and result controls. Arrows remain usable
        # even if a PDF candidate button or the close button owns focus.
        self.navigation_focused = False
        self.navigation_sequence = 0
        self.key_target = ft.TextField(value='', read_only=True, ignore_up_down_keys=True,
            enable_interactive_selection=False, width=1, height=1, opacity=0,
            border=ft.InputBorder.NONE, content_padding=0,
            on_focus=lambda e:setattr(self, 'navigation_focused', True),
            on_blur=lambda e:setattr(self, 'navigation_focused', False))
        previous_keyboard_handler = self.page.on_keyboard_event
        async def route_key(event):
            if self.can_navigate():
                key = event.key.replace(' ', '')
                if key == 'Escape':
                    self.toggle_preview()
                    return
                if not self.navigation_focused:
                    if key not in ('ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'):
                        return
                    await self.focus_navigation()
                self.navigation_sequence += 1
                sequence = self.navigation_sequence
                if key in ('ArrowUp', 'ArrowDown'):
                    held = self.held_vertical_key(event)
                    if held:
                        self.page.run_task(self.repeat_navigation, event, sequence, held)
                await self.navigate_key(event)
            elif previous_keyboard_handler:
                result = previous_keyboard_handler(event)
                if inspect.isawaitable(result):
                    await result
        self.page.on_keyboard_event = route_key
        self.toolbar.controls.append(self.key_target)
        self.list_host = ft.Container(self.list_panel, expand=True)
        self.body = ft.Row([self.list_host, self.preview_panel], expand=True, spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        self.tab_bar = ft.TabBar(tabs=[self.result_tab, self.stock_tab])
        self.tabs = ft.Tabs(length=2, selected_index=0, on_change=self.on_tab_change, expand=True,
            content=ft.Column([self.tab_bar, self.toolbar, self.body],
                expand=True, spacing=6, horizontal_alignment=ft.CrossAxisAlignment.STRETCH))
        self.view = ft.Container(self.tabs, expand=True, visible=False,
            alignment=ft.Alignment.TOP_LEFT)

    @staticmethod
    def core_columns(controls):
        widths = [106, None, 104, None, 96]
        return ft.Row([ft.Container(c, width=w) for c,w in zip(controls,widths)],
            expand=True, spacing=8, vertical_alignment=ft.CrossAxisAlignment.START)

    def on_list_scroll(self, event):
        self.scroll_offset = event.pixels
        self.viewport_height = event.viewport_dimension

    def groups(self):
        return self.items if self.stock_view else self.results

    def sync_selection(self):
        selected = sum(i['selected'] for i in self.items) if self.stock_view else len(self.selection)
        self.count.value = f'{len(self.groups())}部品 / 選択 {selected}部品'
        for group in self.groups():
            cached = self.row_cache.get(group['key'])
            if cached:
                cached['check'].value = group['selected'] if self.stock_view else group['key'] in self.selection

    def render(self):
        groups = self.groups()
        self.stock_tab.label = f'部品ストック（{len(self.items)}）'
        self.add_button.visible = not self.stock_view
        self.remove_button.visible = self.export_button.visible = self.stock_view
        stacked = {g['key'] for g in self.items}
        updated = {}
        for group in groups:
            key = group['key']
            # Selection-only changes retain the actual row controls and scroll state.
            snapshot = {k:v for k,v in group.items() if k != 'selected'}
            signature = (snapshot, self.stock_view, key in stacked, key in self.expanded_keys)
            cached = self.row_cache.get(key)
            if cached is None or cached['signature'] != signature:
                cached = self.make_row(group, key in stacked)
                cached['signature'] = signature
            updated[key] = cached
        self.row_cache = updated
        if self.active_key not in updated:
            self.active_key = None
        rows = [updated[g['key']]['row'] for g in groups]
        if [id(c) for c in self.list.controls] != [id(c) for c in rows]:
            self.list.controls = rows
        self.sync_selection()
        self.resize_rows()
        self.highlight_active()

    def make_row(self, group, stacked):
        key = group['key']
        async def check(event):
            if self.normal.busy():
                return
            if self.stock_view:
                if not await self.commit([dict(g, selected=bool(event.control.value)) if g['key']==key else dict(g) for g in self.items]):
                    self.sync_selection()
                    self.page.update()
            else:
                self.selection.add(key) if event.control.value else self.selection.discard(key)
                self.sync_selection()
                self.page.update()
            await self.focus_navigation()
        checkbox = ft.Checkbox(on_change=check)
        actions = [checkbox]
        if not self.stock_view and stacked:
            actions.append(ft.Text('ストック済', size=12, color=ft.Colors.PRIMARY,
                tooltip='登録済みです。選択して追加すると、この検索で見つかった使用ASSY・PDF候補を追記できます。'))
        if self.stock_view:
            async def up(e):
                await self.move(key, -1)
            async def down(e):
                await self.move(key, 1)
            actions.append(ft.Row([ft.IconButton(ft.Icons.ARROW_UPWARD, icon_size=16, width=28, height=28, tooltip='上へ', on_click=up),
                ft.IconButton(ft.Icons.ARROW_DOWNWARD, icon_size=16, width=28, height=28, tooltip='下へ', on_click=down)], spacing=0))
        def text(value, lines=2):
            return ft.Text(value, size=14, max_lines=lines, overflow=ft.TextOverflow.ELLIPSIS, tooltip=value)
        identity = ft.Container(text(group['identifier'] or '番号なし'), padding=ft.Padding.symmetric(vertical=6))
        pdfs = group['pdfs']
        expanded = key in self.expanded_keys
        pdf_controls = []
        for path in (pdfs if expanded else pdfs[:2]):
            async def folder(e, path=path):
                if not self.normal.busy():
                    await self.normal.open_pdf(path, True)
            async def launch(e, path=path):
                if not self.normal.busy():
                    await self.normal.open_pdf(path, False)
            pdf_controls.append(ft.Column([
                ft.Container(ft.Text(str(Path(path).parent), size=12, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    on_click=folder, tooltip=str(Path(path).parent), ink=True),
                ft.Container(ft.Text(Path(path).name, size=14, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, color=ft.Colors.PRIMARY),
                    on_click=launch, tooltip=path, ink=True),
            ], spacing=0, height=40))
        if not pdfs:
            pdf_controls.append(text(group['pdf_status']))
        if len(pdfs)>2:
            pdf_controls.append(ft.TextButton('折りたたむ' if expanded else f'他{len(pdfs)-2}件を表示',
                on_click=lambda e:self.expand_row(key), height=28))
        assy, assy_height = self.assy_cell(group, expanded)
        pdf_height = max(40, min(2,len(pdfs))*40 if not expanded else len(pdfs)*40) + (28 if len(pdfs)>2 else 0)
        core = self.core_columns([identity, ft.Container(text(group['name']), padding=ft.Padding.symmetric(vertical=6)),
            ft.Container(text(group['material'] or '未記載'), padding=ft.Padding.symmetric(vertical=6)),
            ft.Column(pdf_controls, spacing=0), ft.Column(actions, spacing=0)])
        row = ft.Container(ft.Row([core, assy], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START),
            # Rebuilt keyed controls are reconciled as frozen by Flet 1.0.1.
            # Rows use object identity; scrolling already uses pixel offsets.
            padding=6,
            border=ft.Border(bottom=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)))
        return dict(row=row, core=core, check=checkbox, assy=assy, base_height=max(72,pdf_height+12), assy_height=assy_height+12)

    def assy_cell(self, group, expanded):
        sheets = OrderedDict()
        seen = set()
        for occurrence in group['occurrences']:
            source = (occurrence['path'], occurrence['sheet'])
            if source in seen:
                continue
            seen.add(source)
            sheets.setdefault(occurrence['sheet'], []).append(occurrence)
        entries = list(sheets.items())
        controls, height = [], 0
        hidden = len(entries)>2 or any(len(v)>3 for _,v in entries)
        for sheet, occurrences in (entries if expanded else entries[:2]):
            labels = []
            for occurrence in (occurrences if expanded else occurrences[:3]):
                async def launch(event, occurrence=occurrence):
                    await self.open_occurrence(occurrence)
                label = occurrence['product_id'] or Path(occurrence['path']).name
                labels.append(ft.Container(ft.Text(label, size=13, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                    color=ft.Colors.ON_SECONDARY_CONTAINER), width=72, height=26, padding=4,
                    bgcolor=ft.Colors.SECONDARY_CONTAINER, border_radius=4, ink=True, on_click=launch,
                    tooltip=self.occurrence_tooltip(occurrence)))
            lines = [ft.Row(labels[i:i+3],spacing=4) for i in range(0,len(labels),3)]
            line_height = max(1,len(lines))*28+4
            controls.append(ft.Container(ft.Row([ft.Text(sheet, size=13, width=110, max_lines=2,
                overflow=ft.TextOverflow.ELLIPSIS, tooltip=sheet), ft.Column(lines, spacing=2)], spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.START), height=line_height,
                border=ft.Border(bottom=ft.BorderSide(1,ft.Colors.OUTLINE_VARIANT))))
            height += line_height
        if hidden:
            controls.append(ft.TextButton('折りたたむ' if expanded else f'… 使用ASSYをすべて表示（{len(seen)}件）',
                height=28, on_click=lambda e:self.expand_row(group['key'])))
            height += 28
        return ft.Container(ft.Column(controls, spacing=0), width=440), height

    @staticmethod
    def occurrence_tooltip(occurrence):
        stamp = occurrence.get('mtime')
        try:
            updated = datetime.fromtimestamp(stamp / 1_000_000_000).strftime('%Y-%m-%d %H:%M:%S') if stamp is not None else '未記録'
        except (TypeError, ValueError, OSError, OverflowError):
            updated = '未記録'
        excel_path = Path(occurrence['path'])
        return f"構成部品表パス：{excel_path.parent.name}\nファイル名：{excel_path.name}\n更新日時：{updated}"

    def expand_row(self, key):
        if self.normal.busy():
            return
        self.expanded_keys.remove(key) if key in self.expanded_keys else self.expanded_keys.add(key)
        self.render()
        self.page.update()
        self.page.run_task(self.focus_navigation)

    async def focus_navigation(self):
        if self.view.visible and not self.normal.busy():
            await self.key_target.focus()

    def first_visible_group(self):
        offset = 0
        for group in self.groups():
            row = self.row_cache[group['key']]['row']
            if offset + row.height > self.scroll_offset:
                return group
            offset += row.height
        return self.groups()[-1] if self.groups() else None

    def resize_rows(self):
        width = self.page.width or 1400
        previous_right = min(660, max(370, width * 0.35))
        # 378px covers the fixed columns, gaps and page/row padding.
        flexible = max(0, width - previous_right - 378)
        name_width = max(90, flexible * 3 / 7 * 0.6)
        pdf_width = max(135, flexible * 4 / 7 * 0.75)
        right_width = max(0, width - 378 - name_width - pdf_width)
        self.heading.controls[0].controls[1].width = name_width
        self.heading.controls[0].controls[3].width = pdf_width
        self.preview_panel.width = right_width
        self.image.width = max(0, right_width - 16)
        compact = self.preview_panel.visible
        self.heading_assy.visible = not compact
        # Row padding consumes 12px; the external preview does not.
        self.heading_assy.width = max(0, right_width - 12)
        for cached in self.row_cache.values():
            cached['core'].controls[1].width = name_width
            cached['core'].controls[3].width = pdf_width
            cached['assy'].visible = not compact
            cached['assy'].width = self.heading_assy.width
            # Keep the same heights on toggle so scroll position remains stable.
            cached['row'].height = max(cached['base_height'],cached['assy_height'])

    def highlight_active(self):
        for key,cached in self.row_cache.items():
            cached['row'].bgcolor = ft.Colors.SURFACE_CONTAINER_HIGHEST if key==self.active_key else None

    async def activate_row(self, key, scroll=False):
        if self.normal.busy() or not self.preview_panel.visible:
            return
        self.active_key = key
        self.highlight_active()
        self.page.update()
        # Arrow events already originate in this listener. Refocusing on every
        # repeat adds an unnecessary native round trip to keyboard navigation.
        if not scroll:
            await self.focus_navigation()
        if self.active_key != key or not self.view.visible or not self.preview_panel.visible or self.normal.busy():
            return
        if scroll:
            offset = 0
            for group in self.groups():
                row = self.row_cache[group['key']]['row']
                if group['key']==key:
                    if offset<self.scroll_offset or offset+row.height>self.scroll_offset+self.viewport_height:
                        await self.list.scroll_to(offset=max(0,offset if offset<self.scroll_offset else offset+row.height-self.viewport_height))
                    break
                offset += row.height
        if self.preview_panel.visible and self.active_key == key:
            group = next((g for g in self.groups() if g['key']==key),None)
            if group:
                await self.show_candidates(group)

    async def navigate_key(self, event):
        if not self.can_navigate():
            return
        arrow = event.key.replace(' ', '')
        if arrow in ('Enter', 'NumpadEnter'):
            await self.open_selected_candidate()
            return
        if arrow == 'ArrowRight':
            group = self.preview_group
            if group and group['key'] == self.active_key and len(group['pdfs']) > 1:
                self.set_candidate_navigation(True)
                self.page.update()
            return
        if arrow == 'ArrowLeft':
            if self.navigating_candidates:
                self.set_candidate_navigation(False)
                self.page.update()
            return
        direction = {'ArrowDown': 1, 'ArrowUp': -1}.get(arrow)
        if direction is None:
            return
        if self.navigating_candidates:
            last = len(self.preview_group['pdfs']) - 1
            index = max(0, min(last, self.candidate_index + direction))
            await self.select_candidate(index)
            return
        keys = [g['key'] for g in self.groups()]
        if not keys:
            return
        index = keys.index(self.active_key) if self.active_key in keys else (-1 if direction>0 else len(keys))
        key = keys[max(0,min(len(keys)-1,index+direction))]
        if key != self.active_key:
            await self.activate_row(key,scroll=True)

    def can_navigate(self):
        return (self.view.visible and self.preview_panel.visible and not self.opening_candidate
                and not self.normal.busy())

    def held_vertical_key(self, event):
        # Flet Page sends the initial keydown but omits OS key-repeat events.
        # Check only the pressed arrow, while this Flet window is foreground.
        if sys.platform != 'win32':
            return None
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        foreground = user32.GetForegroundWindow
        foreground.restype = wintypes.HWND
        hwnd = foreground()
        title = ctypes.create_unicode_buffer(256)
        if not hwnd or not user32.GetWindowTextW(wintypes.HWND(hwnd), title, len(title)):
            return None
        if title.value != self.page.title:
            return None
        arrow = 0x26 if event.key.replace(' ', '') == 'ArrowUp' else 0x28
        return lambda: foreground() == hwnd and bool(user32.GetAsyncKeyState(arrow) & 0x8000)

    async def repeat_navigation(self, event, sequence, held):
        await asyncio.sleep(0.4)
        while (sequence == self.navigation_sequence and self.can_navigate()
               and held()):
            await self.navigate_key(event)
            await asyncio.sleep(0.075)

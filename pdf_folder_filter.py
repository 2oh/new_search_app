"""Inline folder hierarchy for PDF filename search."""
from collections import defaultdict

import flet as ft


class FolderFilter:
    def __init__(self, page, limit):
        self.page, self.limit = page, limit
        self.draft, self.expanded = set(), set()
        self.matches = self.on_apply = self.on_close = None
        self.require_folder = False
        self.children, self.counts = {}, {}
        self.listing = ft.ListView(height=200, spacing=0, build_controls_on_demand=True)
        self.count_label = ft.Text(size=13, expand=True)
        self.apply_button = ft.Button('適用', on_click=self.apply)
        self.panel = ft.Container(ft.Column([
            ft.Text('複数選択できます。親フォルダを選ぶと配下も対象になります。', size=13),
            self.listing,
            ft.Row([self.count_label, ft.TextButton('選択解除', on_click=self.reset),
                    ft.TextButton('閉じる', on_click=self.dismiss), self.apply_button], spacing=8),
        ], spacing=4), margin=ft.Margin.only(left=210), width=650, padding=10,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT), border_radius=8, visible=False)

    def open(self, matches, selected, *, require_folder, on_apply, on_close):
        self.matches = matches
        self.on_apply, self.on_close = on_apply, on_close
        self.require_folder = require_folder
        children = defaultdict(set)
        counts = defaultdict(int)
        for folder, records in matches.by_folder.items():
            if not folder:
                counts[()] = len(records)
            for depth in range(1, len(folder) + 1):
                node = folder[:depth]
                children[node[:-1]].add(node)
                counts[node] += len(records)
        self.counts = counts
        self.children = {parent: sorted(folders, key=lambda node: (node[-1].casefold(), node[-1]))
                         for parent, folders in children.items()}
        self.draft = set(selected).intersection(counts)
        self.expanded = {folder[:depth] for folder in self.draft for depth in range(1, len(folder))}
        self.panel.visible = True
        self.refresh()

    def close(self):
        if self.panel.visible:
            self.panel.visible = False
            self.listing.controls = []
            self.matches = self.on_apply = self.on_close = None
            self.draft.clear()
            self.expanded.clear()
            self.children, self.counts = {}, {}

    def dismiss(self, event=None):
        if self.panel.visible and self.on_close:
            self.on_close()

    def apply(self, event=None):
        if self.panel.visible and not self.apply_button.disabled:
            self.on_apply(set(self.draft))

    def expand(self, node):
        self.expanded.remove(node) if node in self.expanded else self.expanded.add(node)
        self.refresh()

    def select(self, node, value):
        if value:
            if node:
                self.draft.difference_update(child for child in tuple(self.draft) if child[:len(node)] == node)
            self.draft.add(node)
        else:
            self.draft.discard(node)
        self.refresh()

    def row(self, node):
        name = node[-1] if node else '（検索先直下）'
        inherited = any(node[:depth] in self.draft for depth in range(1, len(node)))
        arrow = (ft.IconButton(ft.Icons.EXPAND_MORE if node in self.expanded else ft.Icons.CHEVRON_RIGHT,
                    on_click=lambda e: self.expand(node), width=32, height=32, tooltip='開閉')
                 if node and node in self.children else ft.Container(width=32))
        checkbox = ft.Checkbox(value=node in self.draft or inherited, disabled=inherited,
            on_change=lambda e: self.select(node, bool(e.control.value)))
        return ft.Row([ft.Container(width=min(192, 16 * max(0, len(node) - 1))), arrow, checkbox,
            ft.Text(name, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                    tooltip=' / '.join(node) or name), ft.Text(f'{self.counts[node]:,}件')], spacing=4)

    def refresh(self):
        if not self.panel.visible:
            return
        rows = [self.row(())] if () in self.counts else []
        pending = list(reversed(self.children.get((), ())))
        while pending:
            node = pending.pop()
            rows.append(self.row(node))
            if node in self.expanded:
                pending.extend(reversed(self.children.get(node, ())))
        self.listing.controls = rows or [ft.Text('該当するフォルダがありません', size=13)]
        count = self.matches.count(self.draft)
        needs_folder = self.require_folder and not self.draft
        self.apply_button.disabled = needs_folder or count > self.limit
        self.count_label.value = (f'フォルダを選択（索引の該当 {count:,}件）' if needs_folder else
            f'対象 {count:,}件' + (f'（{self.limit}件以下に絞ってください）' if count > self.limit else ''))
        self.page.update()

    def reset(self, event=None):
        self.draft.clear()
        self.refresh()

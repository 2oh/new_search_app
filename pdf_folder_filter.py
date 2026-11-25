"""Folder chooser for the current PDF filename search."""
from collections import defaultdict

import flet as ft


def show_folder_filter(page, matches, selected, limit, apply_filter):
    draft = set(selected)
    expanded = {folder[:depth] for folder in draft for depth in range(1, len(folder))}
    children = defaultdict(set)
    counts = defaultdict(int)
    for folder, records in matches.by_folder.items():
        if not folder:
            counts[()] = len(records)
        for depth in range(1, len(folder) + 1):
            node = folder[:depth]
            children[node[:-1]].add(node)
            counts[node] += len(records)
    children = {parent: sorted(folders, key=lambda node: node[-1].casefold())
                for parent, folders in children.items()}
    listing = ft.ListView(height=min(460, max(280, (page.height or 800) - 330)),
        spacing=0, build_controls_on_demand=True)
    count_label = ft.Text()

    def apply(event):
        page.pop_dialog()
        apply_filter(draft)

    apply_button = ft.Button('適用', on_click=apply)

    def expand(node):
        expanded.remove(node) if node in expanded else expanded.add(node)
        refresh()

    def select(node, value):
        if value:
            # A parent already includes its descendants.
            if node:
                draft.difference_update(child for child in tuple(draft) if child[:len(node)] == node)
            draft.add(node)
        else:
            draft.discard(node)
        refresh()

    def row(node):
        name = node[-1] if node else '（検索先直下）'
        inherited = any(node[:depth] in draft for depth in range(1, len(node)))
        arrow = (ft.IconButton(ft.Icons.EXPAND_MORE if node in expanded else ft.Icons.CHEVRON_RIGHT,
                    on_click=lambda e: expand(node), width=32, height=32, tooltip='開閉')
                 if node and node in children else ft.Container(width=32))
        checkbox = ft.Checkbox(value=node in draft or inherited, disabled=inherited,
            on_change=lambda e: select(node, bool(e.control.value)))
        return ft.Row([ft.Container(width=16 * max(0, len(node) - 1)), arrow, checkbox,
            ft.Text(name, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                    tooltip=' / '.join(node) or name), ft.Text(f'{counts[node]:,}件')], spacing=4)

    def refresh():
        rows = [row(())] if () in counts else []
        pending = list(reversed(children.get((), ())))
        while pending:
            node = pending.pop()
            rows.append(row(node))
            if node in expanded:
                pending.extend(reversed(children.get(node, ())))
        listing.controls = rows
        count = matches.count(draft)
        apply_button.disabled = count > limit
        count_label.value = f'対象 {count:,}件' + (f'（{limit}件以下に絞ってください）' if count > limit else '')
        page.update()

    def reset(event):
        draft.clear()
        refresh()

    dialog = ft.AlertDialog(modal=True, title=ft.Text('フォルダで絞り込み'),
        content=ft.Container(ft.Column([ft.Text('複数選択できます。親フォルダを選ぶと配下も対象になります。'),
            count_label, listing], tight=True), width=680),
        actions=[ft.TextButton('選択解除', on_click=reset),
                 ft.TextButton('キャンセル', on_click=lambda e: page.pop_dialog()), apply_button])
    page.show_dialog(dialog)
    refresh()

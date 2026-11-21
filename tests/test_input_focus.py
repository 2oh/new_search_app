import unittest
from types import SimpleNamespace
import flet as ft
from input_focus import InputFocus


class InputFocusTests(unittest.IsolatedAsyncioTestCase):
    async def test_window_restore_preserves_partial_unicode_selection(self):
        page = SimpleNamespace(window=SimpleNamespace(), update=lambda: None)
        keeper = InputFocus(page)
        field = keeper.bind(ft.TextField(value='A😀BC'))
        field.on_focus(None)
        selected = ft.TextSelection(base_offset=1, extent_offset=3)
        field.on_selection_change(SimpleNamespace(selection=selected))
        await keeper.window_event(SimpleNamespace(type=ft.WindowEventType.BLUR))
        field.selection = ft.TextSelection(base_offset=0, extent_offset=5)
        await keeper.window_event(SimpleNamespace(type=ft.WindowEventType.FOCUS))
        self.assertEqual((field.selection.base_offset, field.selection.extent_offset), (1, 3))

    async def test_changed_text_or_different_field_not_overridden(self):
        page = SimpleNamespace(window=SimpleNamespace(), update=lambda: None)
        keeper = InputFocus(page)
        field = keeper.bind(ft.TextField(value='abc', selection=ft.TextSelection(3,3)))
        field.on_focus(None)
        await keeper.window_event(SimpleNamespace(type=ft.WindowEventType.BLUR))
        field.value = 'new'
        field.selection = ft.TextSelection(1,1)
        await keeper.window_event(SimpleNamespace(type=ft.WindowEventType.FOCUS))
        self.assertEqual(field.selection.base_offset, 1)
        await keeper.window_event(SimpleNamespace(type=ft.WindowEventType.BLUR))
        other = keeper.bind(ft.TextField(value='other'))
        other.on_focus(None)
        await keeper.window_event(SimpleNamespace(type=ft.WindowEventType.FOCUS))
        self.assertIsNone(other.selection)

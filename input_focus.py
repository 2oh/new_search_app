"""Remember editable field selections while another desktop window is active."""
import asyncio
from copy import copy
import flet as ft


class InputFocus:
    def __init__(self, page):
        self.page = page
        self.active = None
        self.saved = None
        self.away = False
        self.generation = 0
        self.restore_preferred_focus = None
        page.window.on_event = self.window_event

    def bind(self, field):
        def focus(e):
            self.active = field
        def selection(e):
            # Subscribing also makes Flet send the current selection to Python.
            if not self.away:
                field.selection = e.selection
        field.on_focus = focus
        field.on_selection_change = selection
        return field

    async def window_event(self, e):
        if e.type == ft.WindowEventType.BLUR:
            self.generation += 1
            field = self.active
            self.saved = (field, field.value, copy(field.selection)) if field is not None else None
            self.away = True
        elif e.type == ft.WindowEventType.FOCUS:
            generation = self.generation
            saved = self.saved
            # Let the native focus/default selection event settle before restoring.
            await asyncio.sleep(0.05)
            if generation != self.generation:
                return
            self.away = False
            self.saved = None
            if self.restore_preferred_focus and await self.restore_preferred_focus():
                return
            if saved:
                field, value, selected = saved
                if field is self.active and field.value == value and selected is not None:
                    field.selection = selected
                    self.page.update()

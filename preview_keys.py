"""Repeat a preview's vertical navigation while its Windows key remains held."""
import asyncio
import sys


VERTICAL_KEYS = ('ArrowUp', 'ArrowDown')


class VerticalKeyRepeat:
    def __init__(self, page, can_navigate, move):
        self.page, self.can_navigate, self.move = page, can_navigate, move
        self.sequence = 0

    def stop(self):
        self.sequence += 1

    def start(self, event):
        self.stop()
        held = self.held_key(event.key.replace(' ', ''))
        if held is not None:
            self.page.run_task(self.run, event, self.sequence, held)

    def held_key(self, key):
        # Flet's page event omits Windows key-repeat events.
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
        arrow = 0x26 if key == 'ArrowUp' else 0x28
        return lambda: foreground() == hwnd and bool(user32.GetAsyncKeyState(arrow) & 0x8000)

    async def run(self, event, sequence, held):
        await asyncio.sleep(0.4)
        while sequence == self.sequence and self.can_navigate() and held():
            await self.move(event)
            await asyncio.sleep(0.075)

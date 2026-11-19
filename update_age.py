"""Dates use the user's local calendar, not elapsed 24-hour blocks."""
from datetime import datetime


def format_updated(value, now=None):
    updated = datetime.fromisoformat(value).astimezone()
    now = now or datetime.now().astimezone()
    days = (now.astimezone().date() - updated.date()).days
    age = '今日' if days == 0 else '昨日' if days == 1 else f'{days}日前' if days > 1 else '未来の日付'
    return updated.strftime('%Y/%m/%d') + f'（{age}）' + updated.strftime(' %H:%M:%S')

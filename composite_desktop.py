"""Open a source sheet read-only in a separate Excel instance."""
from pathlib import Path


def open_sheet(path, sheet_name):
    if not Path(path).is_file():
        raise FileNotFoundError(f'元Excelが見つかりません：{path}')
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    app = book = sheet = None
    try:
        app = win32com.client.DispatchEx('Excel.Application')
        app.AutomationSecurity = 3
        app.EnableEvents = False
        book = app.Workbooks.Open(str(Path(path).resolve()), UpdateLinks=0, ReadOnly=True)
        sheet = book.Worksheets(sheet_name)
        sheet.Activate()
        app.Visible = True
        app.UserControl = True
        app.WindowState = -4137
        import ctypes
        ctypes.windll.user32.ShowWindow(app.Hwnd, 3)
        ctypes.windll.user32.SetForegroundWindow(app.Hwnd)
    except Exception:
        if book is not None:
            book.Close(False)
        if app is not None:
            app.Quit()
        raise
    finally:
        sheet = book = app = None
        pythoncom.CoUninitialize()

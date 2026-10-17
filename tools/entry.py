"""Frozen launcher: private settings beside the executable, bundled Flet client."""
import asyncio
import os
from pathlib import Path
import sys
import traceback

import flet as ft
import main as application


def run():
    bundle = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
    home = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path.cwd()
    os.environ['FLET_VIEW_PATH'] = str(bundle / 'flet-client')
    os.chdir(home)
    if '--self-test' in sys.argv:
        from frozen_selftest import run_test
        destination = Path(sys.argv[sys.argv.index('--self-test') + 1]).resolve()
        asyncio.run(run_test(application, bundle, destination))
        return

    def main(page):
        application.main(page)

    ft.run(main, assets_dir=str(bundle / 'assets'))


if __name__ == '__main__':
    try:
        run()
    except Exception:
        target = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path.cwd()
        (target / 'startup-error.log').write_text(traceback.format_exc(), encoding='utf-8')
        raise

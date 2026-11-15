"""Build the console-only PDF index updater in the existing build environment."""
from pathlib import Path
import subprocess
import sys


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    build = root / 'build' / 'pdf-index'
    build.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile',
                    '--console', '--name', 'pdf_index_update', '--distpath', str(root / 'dist'),
                    '--workpath', str(build), '--specpath', str(build),
                    '--paths', str(root), str(root / 'pdf_index_batch.py')], cwd=root, check=True)

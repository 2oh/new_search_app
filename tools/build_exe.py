"""Build with the activated Python environment. Run from any working directory."""
import argparse
import ast
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import re
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = args.project.resolve()
    output = (args.output or root / 'dist').resolve()
    source = root / 'main.py'
    tree = ast.parse(source.read_text(encoding='utf-8-sig'))
    app_version = next(ast.literal_eval(n.value) for n in tree.body
                       if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'APP_VERSION' for t in n.targets))
    if not re.fullmatch(r'v\d+\.\d+\.\d+', app_version):
        raise ValueError('APP_VERSION must have the form v1.1.0')
    if version('flet') != '1.0.1' or version('flet-desktop') != '1.0.1':
        raise RuntimeError('Use the tested Flet 1.0.1 environment')
    from flet_desktop import ensure_client_cached
    client = Path(ensure_client_cached()) / 'flet'
    if not (client / 'flet.exe').is_file():
        raise FileNotFoundError(client / 'flet.exe')
    tools = Path(__file__).resolve().parent
    name = f'図面PDF検索結合ツール ({app_version})'
    work = output.parent / 'build' / 'onefile'
    work.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--windowed',
               '--name', name, '--distpath', str(output), '--workpath', str(work),
               '--specpath', str(work), '--paths', str(root),
               '--icon', str(root / 'assets/app_icon.ico'),
               '--add-data', f'{root / "assets"};assets',
               '--add-data', f'{client};flet-client',
               '--add-data', f'{tools / "fixtures/app_a_excel_test.xlsx"};selftest_data',
               '--add-data', f'{tools / "fixtures/pdfs"};selftest_data/pdfs',
               '--hidden-import', 'flet_desktop', '--collect-data', 'flet',
               '--copy-metadata', 'flet', '--copy-metadata', 'flet-desktop', str(tools / 'entry.py')]
    subprocess.run(command, cwd=root, check=True)
    exe = output / (name + '.exe')
    report = {'version': app_version, 'python': sys.version, 'python_executable': sys.executable,
              'main_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'exe_sha256': hashlib.sha256(exe.read_bytes()).hexdigest(),
              'packages': {n: version(n) for n in ('flet', 'flet-desktop', 'pyinstaller', 'pandas', 'openpyxl', 'pypdf', 'PyMuPDF')}}
    exe.with_suffix('.build.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Built: {exe}')


if __name__ == '__main__':
    main()

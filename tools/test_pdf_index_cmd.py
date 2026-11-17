"""Exercise both distributed CMD launchers against the built updater EXE."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def run(root, exe):
    with tempfile.TemporaryDirectory(prefix='pdf-cmd-') as temp:
        base = Path(temp)
        install = base / '日本語 space & folder'
        install.mkdir()
        for name in ('daily_pdf_index.cmd', 'manual_pdf_index.cmd'):
            shutil.copy2(root / name, install / name)
        def command(name):
            shell = os.environ.get('COMSPEC', r'C:\Windows\System32\cmd.exe')
            result = subprocess.run(f'"{shell}" /d /s /c ""{install / name}""', cwd=base,
                                    input=b'\r\n', capture_output=True, timeout=60)
            return result.returncode, result.stdout + result.stderr
        for name in ('daily_pdf_index.cmd', 'manual_pdf_index.cmd'):
            code, output = command(name)
            assert code == 2 and b'Missing' in output, (code, output)
        shutil.copy2(exe, install / 'pdf_index_update.exe')
        for name in ('daily_pdf_index.cmd', 'manual_pdf_index.cmd'):
            code, output = command(name)
            assert code == 2 and b'Missing' in output, (code, output)
        pdfs = base / 'PDF # %'
        pdfs.mkdir()
        (pdfs / '12345.pdf').write_bytes(b'filename-only test')
        (pdfs / '.pdf').write_bytes(b'filename-only test')
        config = install / 'pdf_index_config.json'
        config.write_text(json.dumps({'root': str(pdfs), 'database': 'storage/index.sqlite',
                                     'publish': 'public', 'logs': 'logs'}), encoding='utf-8')
        for name in ('daily_pdf_index.cmd', 'manual_pdf_index.cmd'):
            code, output = command(name)
            assert code == 0 and b'v1.3.1' in output, (code, output)
        manifest = install / 'public/pdf-latest.json'
        before = manifest.read_bytes()
        logs = next((install / 'logs').glob('*.log')).read_text(encoding='utf-8')
        assert str(pdfs / '.pdf') in logs and '除外：1件' in logs
        (pdfs / '12345.pdf').unlink()
        for name in ('daily_pdf_index.cmd', 'manual_pdf_index.cmd'):
            code, output = command(name)
            assert code == 1, (code, output)
            if name.startswith('manual'):
                assert b'Finished. Exit code: 1' in output
        assert before == manifest.read_bytes()
        print('PASS: both CMD launchers; missing files=2, success=0, failure=1; Japanese/spaces/& path; cwd independence; skip log; old publication preserved')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    run(root, (args.exe or root / 'dist/pdf_index_update.exe').resolve())

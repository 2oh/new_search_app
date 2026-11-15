"""Daily PDF index builder. Run with --config <json>; Python not needed in EXE."""
import argparse
from datetime import datetime
import json
import logging
from pathlib import Path
import sys

from pdf_catalog import ingest, operation_lock, publish


def main(argv=None):
    parser = argparse.ArgumentParser(description='PDF索引を作成して公開します')
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args(argv)
    logger = logging.getLogger('pdf-index')
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.addHandler(logging.StreamHandler(sys.stdout))
    try:
        config_file = args.config.absolute()
        config = json.loads(config_file.read_text(encoding='utf-8-sig'))
        paths = {}
        for key in ('root', 'database', 'publish', 'logs'):
            value = config.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f'設定に {key} が必要です')
            path = Path(value)
            paths[key] = path if path.is_absolute() else config_file.parent / path
        if paths['database'].suffix.lower() not in ('.sqlite', '.db'):
            raise ValueError('databaseはDBファイル名まで指定してください')
        paths['logs'].mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(paths['logs'] / f'pdf-index-{datetime.now():%Y%m%d}.log', encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        logger.addHandler(handler)
        with operation_lock(paths['database'].with_suffix('.update.lock')):
            logger.info('PDF索引の更新開始')
            ingest(paths['root'], paths['database'], logger.info)
            published = publish(paths['database'], paths['publish'])
            logger.info('公開完了：%s', published['file'])
        return 0
    except Exception:
        logger.exception('PDF索引更新・公開に失敗しました。前回の公開版を維持します。')
        return 1
    finally:
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)


if __name__ == '__main__':
    raise SystemExit(main())

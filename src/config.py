from __future__ import annotations

import json
from pathlib import Path

# ============================================================
# 出力ファイルの設定（ディレクトリ & ファイル名フォーマット）
# ============================================================

DEFAULT_CONFIG = {
    # 出力先ディレクトリ（スクリプトからの相対 or 絶対パス）
    "output_dir": "outputs",
    # {input_stem}: 入力tf.jsonのファイル名（拡張子なし）
    # {timestamp}: yyyyMMdd-hhmm 形式の現在時刻
    "markdown_name_format": "{input_stem}_params_{timestamp}.md",
    "excel_name_format": "{input_stem}_params_{timestamp}.xlsx",
}

CONFIG_FILE_NAME = "config.json"


def load_config(config_path: Path) -> dict:
    """
    設定ファイル(JSON)を読み込み、DEFAULT_CONFIGにマージして返す。
    読み込みに失敗した場合や存在しない場合は DEFAULT_CONFIG をそのまま返す。
    """
    config = DEFAULT_CONFIG.copy()

    if config_path.is_file():
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                config.update(loaded)
        except Exception as e:
            print(f"[WARN] 設定ファイルの読み込みに失敗しました ({config_path}): {e}")

    return config

import argparse
import chardet
from pathlib import Path
from dotenv import load_dotenv

from datetime import datetime

from src.config import DEFAULT_CONFIG, CONFIG_FILE_NAME, load_config
from src.tfstate import load_tf_json
from src.layout import (
    load_previous_layout,
    generate_layout_csv,
)
from src.markdown import (
    filter_layout_csv_text,
    generate_markdown_from_tf_json,
)
from src.excel import write_excel_from_markdown

load_dotenv()  # .envファイルを自動読み込み


# ============================================================
# メイン処理
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Terraform JSON → パラシメーカー(ParaSheet Maker)用パラメータシート(Markdown + Excel)生成ツール"
    )
    parser.add_argument("input", help="terraform show -json の出力ファイル (tf.json)")
    parser.add_argument(
        "-o",
        "--output",
        help="出力するMarkdownファイル名（デフォルト: parameter_sheet.md）",
    )
    parser.add_argument(
        "--model",
        default="gpt-4.1-mini",
        help="利用するOpenAIモデル名（デフォルト: gpt-4.1-mini）",
    )
    parser.add_argument(
        "--excel",
        help="生成するExcelファイル名（指定しない場合はMarkdownと同じ名前で拡張子のみ .xlsx）",
    )
    parser.add_argument(
        "--mode",
        choices=["generate", "analyze"],
        default="generate",
        help="処理モード: analyze=レイアウト用CSV生成, generate=Markdown+Excel生成（デフォルト: generate）",
    )
    parser.add_argument(
        "--ai-header",
        action="store_true",
        help="analyzeモード時にAIを使ってheader列を自動調整する",
    )
    parser.add_argument(
        "--ai-sheet",
        action="store_true",
        help="analyzeモード時にAIを使って関連resource_typeを同一シートにまとめ、シート名もAWSマネコン準拠で自動提案する",
    )
    parser.add_argument(
        "--layout-csv",
        default="layout_template.csv",
        help="レイアウト定義CSVファイルパス（デフォルト: layout_template.csv）",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="詳細なデバッグログを出力する",
    )
    args = parser.parse_args()

    # スクリプトのディレクトリ & 設定ファイル読み込み
    script_dir = Path(__file__).resolve().parent
    config_path = script_dir / CONFIG_FILE_NAME
    config = load_config(config_path)

    input_path = Path(args.input)
    tf_json = load_tf_json(input_path)

    print("[INFO] 入力JSON :", input_path)
    print("[INFO] モード   :", args.mode)

    # analyze モード: tf.json からレイアウト定義CSVを生成して終了
    if args.mode == "analyze":
        layout_csv_path = Path(args.layout_csv)

        # 既存レイアウトを読み込み（あれば）
        prev_layout_map = load_previous_layout(layout_csv_path)

        # AI を使うかどうか
        use_ai_header = bool(args.ai_header)
        use_ai_sheet = bool(args.ai_sheet)

        generate_layout_csv(
            tf_json,
            layout_csv_path,
            prev_layout_map=prev_layout_map,
            use_ai_header=use_ai_header,
            use_ai_sheet=use_ai_sheet,
            model=args.model,
            verbose=args.verbose,
        )
        print("[DONE] レイアウト定義CSVを出力しました:", layout_csv_path)
        return

    # ここから generate モード: LLMでMarkdownを生成し、Excelに変換
    # 出力ディレクトリ決定（相対指定ならスクリプトからの相対パス）
    raw_output_dir = Path(config.get("output_dir", DEFAULT_CONFIG["output_dir"]))
    if raw_output_dir.is_absolute():
        output_dir = raw_output_dir
    else:
        output_dir = (script_dir / raw_output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # タイムスタンプ (yyyyMMdd-hhmm)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M")
    input_stem = input_path.stem

    # Markdown ファイル名
    if args.output:
        md_filename = args.output
    else:
        md_format = config.get("markdown_name_format", DEFAULT_CONFIG["markdown_name_format"])
        md_filename = md_format.format(input_stem=input_stem, timestamp=timestamp)

    # Excel ファイル名
    if args.excel:
        excel_filename = args.excel
    else:
        excel_format = config.get("excel_name_format", DEFAULT_CONFIG["excel_name_format"])
        excel_filename = excel_format.format(input_stem=input_stem, timestamp=timestamp)

    # 実際のパス（どちらも output_dir 配下）
    output_path = output_dir / md_filename
    excel_path = output_dir / excel_filename

    layout_csv_path = Path(args.layout_csv)
    if not layout_csv_path.exists():
        raise FileNotFoundError(
            f"レイアウト定義CSVが見つかりません: {layout_csv_path} "
            "先に --mode analyze で layout_template.csv を生成し、編集してください。",
        )

    # 文字コード自動判定：layout_template.csvがUTF-8以外、Shift-JIS/CP932/EUC-JPでも問題なく動くようにする
    raw_bytes = layout_csv_path.read_bytes()
    detected = chardet.detect(raw_bytes)
    encoding = detected.get("encoding") or "utf-8"
    print(f"[INFO] layout_csv の推定エンコーディング: {encoding}")

    layout_csv_text = raw_bytes.decode(encoding, errors="replace")

    # required=1 が1つも無い sheet_name はCSVから除外
    layout_csv_text = filter_layout_csv_text(layout_csv_text)

    print("[INFO] 出力MD   :", output_path)
    print("[INFO] 出力Excel:", excel_path)
    print("[INFO] レイアウトCSV:", layout_csv_path)
    print("[INFO] Markdown生成: Pythonロジックで実施（--model は現在未使用）")

    # LLM ではなく Python ロジックで Markdown を生成
    md_text = generate_markdown_from_tf_json(tf_json, layout_csv_text)

    # Markdown出力
    output_path.write_text(md_text, encoding="utf-8")
    print("[DONE] Markdown を出力しました:", output_path)

    # Excel出力
    write_excel_from_markdown(md_text, excel_path)
    print("[DONE] Excel を出力しました:", excel_path)


if __name__ == "__main__":
    main()

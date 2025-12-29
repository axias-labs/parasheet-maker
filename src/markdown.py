from __future__ import annotations

import csv
import io
import json

from src.tfstate import extract_resources


# ============================================================
# Markdown生成
# ============================================================

def filter_layout_csv_text(layout_csv_text: str) -> str:
    """
    layout_template.csv の内容から、

    - 「全行 requiredが空 の sheet_name」は丸ごと削除
    - 残す sheet_name についても「required=1 の列だけ」を残す

    というフィルタをかけたCSVテキストを返す。
    """
    if not layout_csv_text.strip():
        return layout_csv_text

    f = io.StringIO(layout_csv_text)
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    if not fieldnames:
        return layout_csv_text

    rows = list(reader)
    if not rows:
        return layout_csv_text

    # sheet_name ごとにグルーピング
    by_sheet: dict[str, list[dict]] = {}
    for r in rows:
        sheet = r.get("sheet_name") or ""
        by_sheet.setdefault(sheet, []).append(r)

    filtered_rows: list[dict] = []

    for sheet, sheet_rows in by_sheet.items():
        # このシートに required=1 が1つでもあれば採用
        has_required = any(
            (r.get("required") or "").strip() == "1"
            for r in sheet_rows
        )
        if not has_required:
            continue

        true_rows = []
        link_rows = []

        for r in sheet_rows:
            required_flag = (r.get("required") or "").strip()

            if required_flag == "1":
                true_rows.append(r)

        if not true_rows:
            continue

        filtered_rows.extend(true_rows)
        filtered_rows.extend(link_rows)

    # もし全部消えちゃった場合は元のCSVをそのまま返す（安全側）
    if not filtered_rows:
        return layout_csv_text

    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames)
    writer.writeheader()
    for r in filtered_rows:
        writer.writerow(r)

    return out.getvalue()


def generate_markdown_from_tf_json(tf_json: dict, layout_csv_text: str) -> str:
    """
    layout_template.csv（既に required=1 の列だけにフィルタ済み）と tf.json から、
    LLM を使わずに Markdown のパラメータシートを生成する。
    """

    # tf.json からリソース一覧を取得
    resources = extract_resources(tf_json)
    resources_by_type: dict[str, list[dict]] = {}
    for res in resources:
        resource_type = res.get("type") or ""
        resources_by_type.setdefault(resource_type, []).append(res)

    # layout CSV をパース
    f = io.StringIO(layout_csv_text)
    reader = csv.DictReader(f)
    layout_rows = list(reader)
    if not layout_rows:
        return ""

    # 元の並び順も保持しておく（order 未指定の列用）
    for idx, row in enumerate(layout_rows):
        row["_orig_index"] = idx

    # sheet_name ごとにレイアウト行をグルーピング（順序はCSVの順を維持）
    sheets: dict[str, list[dict]] = {}
    for row in layout_rows:
        sheet = (row.get("sheet_name") or "").strip()
        if not sheet:
            continue
        sheets.setdefault(sheet, []).append(row)

    # values から "a.b.c" 形式の attribute_path で値を取り出すヘルパー
    def get_value_by_path(values: dict, path: str):
        if not path:
            return None
        cur = values
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return None
        return cur

    # Markdown 用に値を文字列化
    def format_value(v):
        if v is None:
            return ""
        # list / dict は JSON 文字列として出す（Excel 側で pretty print させるため）
        if isinstance(v, (list, dict)):
            return json.dumps(v, ensure_ascii=False)
        return str(v)

    md_lines: list[str] = []

    for sheet_name, sheet_rows in sheets.items():
        if not sheet_rows:
            continue

        # order でソート（今までどおり）
        def row_sort_key(r: dict):
            order_str = (r.get("order") or "").strip()
            if order_str != "":
                try:
                    return (0, int(order_str))
                except ValueError:
                    return (0, order_str)
            return (1, r.get("_orig_index", 0))

        # CSV登場順（元の順）を保持したままresource_typeの並びを決める用
        sheet_rows_in_csv_order = sheet_rows

        # 列の並び（orderソート）
        sheet_rows_sorted = sorted(sheet_rows, key=row_sort_key)

        # target_types は「CSV順」から作る
        target_types = []
        for r in sheet_rows_in_csv_order:
            if (r.get("required") or "").strip() != "1":
                continue
            rt = (r.get("resource_type") or "").strip()
            if rt and rt not in target_types:
                target_types.append(rt)

        md_lines.append(f"## {sheet_name}")
        md_lines.append("")

        for target_type in target_types:
            type_cols_all = [r for r in sheet_rows_sorted if (r.get("resource_type") or "").strip() == target_type]
            visible_cols = [r for r in type_cols_all if (r.get("required") or "").strip() == "1"]
            if not visible_cols:
                continue

            # resource_type内の列を order でソート
            visible_cols = sorted(visible_cols, key=row_sort_key)

            md_lines.append(f"@resource_type {target_type}")
            md_lines.append("")

            headers = [(r.get("header") or "") for r in visible_cols]
            md_lines.append("| " + " | ".join(headers) + " |")
            md_lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

            for res in resources_by_type.get(target_type, []):
                values = res.get("values") or {}
                row_cells = []
                for col in visible_cols:
                    attribute_path = (col.get("attribute_path") or "").strip()
                    v = get_value_by_path(values, attribute_path)
                    row_cells.append(format_value(v))
                md_lines.append("| " + " | ".join(row_cells) + " |")

            md_lines.append("")

    return "\n".join(md_lines)

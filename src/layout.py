from __future__ import annotations

import os
import csv
import io
from pathlib import Path
import chardet

from src.tfstate import (
    extract_resources,
    _iter_attribute_paths,
    _is_effective_value,
    _collect_attr_values,
)
from src.ai import (
    suggest_headers_with_ai,
    suggest_sheets_with_ai,
    suggest_orders_with_ai,
)


# ============================================================
# sheet_name 決定用：主要 resource_type 選定
# ============================================================

def pick_primary_resource_type(
    rts: list[str],
    type_counts: dict[str, int],
) -> str:
    if not rts:
        return ""

    excluded_suffixes = (
        "_attachment",
        "_association",
        "_rule",
        "_permission",
        "_grant",
        "_membership",
        "_binding",
        "_mapping",
        "_route",
    )

    def is_excluded(rt: str) -> bool:
        rt = (rt or "").strip()
        if not rt:
            return True
        if any(rt.endswith(suf) for suf in excluded_suffixes):
            return True
        if "policy_attachment" in rt:
            return True
        if rt in ("aws_security_group_rule", "aws_network_acl_rule"):
            return True
        return False

    candidates = [rt for rt in rts if not is_excluded(rt)]
    if not candidates:
        candidates = list(rts)

    parent_priority = [
        "aws_vpc",
        "aws_iam_role",
        "aws_security_group",
        "aws_s3_bucket",
        "aws_kms_key",
        "aws_lb",
        "aws_alb",
        "aws_nlb",
    ]
    for p in parent_priority:
        if p in candidates:
            return p

    candidates_sorted = sorted(candidates, key=lambda x: (-type_counts.get(x, 0), x))
    return candidates_sorted[0]


# ============================================================
# order の最終整形（1..N）
# ============================================================

def renumber_orders_for_type(type_rows: list[dict]) -> None:
    with_order: list[tuple[int, dict]] = []
    without_order: list[dict] = []

    for row in type_rows:
        raw = (row.get("order") or "").strip()
        try:
            with_order.append((int(raw), row))
        except ValueError:
            without_order.append(row)

    with_order.sort(key=lambda x: x[0])
    ordered_rows = [r for _, r in with_order] + without_order

    for idx, row in enumerate(ordered_rows, start=1):
        row["order"] = str(idx)

    type_rows[:] = ordered_rows


# ============================================================
# 既存 layout_template.csv の読み込み
# ============================================================

def load_previous_layout(csv_path: Path) -> dict[tuple[str, str], dict]:
    if not csv_path.exists():
        return {}

    raw_bytes = csv_path.read_bytes()
    detected = chardet.detect(raw_bytes)
    encoding = detected.get("encoding") or "utf-8"

    f = io.StringIO(raw_bytes.decode(encoding, errors="replace"))
    reader = csv.DictReader(f)

    prev_map: dict[tuple[str, str], dict] = {}
    for row in reader:
        rt = (row.get("resource_type") or "").strip()
        ap = (row.get("attribute_path") or "").strip()
        if rt and ap:
            prev_map[(rt, ap)] = row
    return prev_map


# ============================================================
# layout_template.csv 生成（analyze モード本体）
# ============================================================

def generate_layout_csv(
    tf_json: dict,
    csv_path: Path,
    prev_layout_map: dict[tuple[str, str], dict] | None = None,
    use_ai_header: bool = False,
    use_ai_sheet: bool = False,
    model: str = "gpt-4.1-mini",
    verbose: bool = False,
):
    """tf.json から resource_type × attribute_path の一覧を作成し、CSVに出力する"""
    resources = extract_resources(tf_json)

    # resource_typeごとの出現数（主要resource_type判定用）
    type_counts: dict[str, int] = {}
    for res in resources:
        rt = (res.get("type") or "").strip()
        if not rt:
            continue
        type_counts[rt] = type_counts.get(rt, 0) + 1
    
    seen = set()  # (resource_type, attribute_path)

    rows: list[dict] = []

    prev_layout_map = prev_layout_map or {}
    new_rows_for_ai: list[dict] = []

    # (resource_type, attribute_path) ごとに
    # 「1つでも有効な値が入っていたか」を記録するマップ
    has_value_map: dict[tuple[str, str], bool] = {}

    for res in resources:
        resource_type = res.get("type") or ""
        values = res.get("values") or {}

        # このリソース内の attribute_path -> [値, 値, ...] を集計
        local_values: dict[str, list] = {}
        _collect_attr_values("", values, local_values)

        # has_value_map を更新（1回でも「有効な値」があれば True）
        for attr_path, vals in local_values.items():
            key = (resource_type, attr_path)
            if has_value_map.get(key):
                continue
            if any(_is_effective_value(v) for v in vals):
                has_value_map[key] = True

        # 既存どおり attribute_path 一覧を取得
        attr_paths = set(_iter_attribute_paths("", values))
        for attribute_path in sorted(attr_paths):
            key = (resource_type, attribute_path)
            if key in seen:
                continue
            seen.add(key)

            prev_row = prev_layout_map.get(key)
            if prev_row:
                # ★ 旧 layout_template から継承（_is_new=False）
                row = {
                    "resource_type": prev_row.get("resource_type", resource_type),
                    "attribute_path": prev_row.get("attribute_path", attribute_path),
                    "sheet_name": prev_row.get("sheet_name", resource_type or "Sheet1"),
                    "header": prev_row.get("header", attribute_path),
                    "required": prev_row.get("required", ""),
                    "order": prev_row.get("order", ""),
                    "_is_new": False,
                }
                rows.append(row)
            else:
                # ★ 新規行：tf.json に1つでも有効な値があれば required="1"、なければ空
                sheet_name = resource_type or "Sheet1"
                header = attribute_path
                required_default = "1" if has_value_map.get(key) else ""
                row = {
                    "resource_type": resource_type,
                    "attribute_path": attribute_path,
                    "sheet_name": sheet_name,
                    "header": header,
                    "required": required_default,
                    "order": "",
                    "_is_new": True,
                }
                new_rows_for_ai.append(row)
                rows.append(row)

    # AI で sheet_name を自動設計（関連resource_typeを同一シートへ寄せる）
    if use_ai_sheet:
        if "OPENAI_API_KEY" not in os.environ:
            print("[WARN] OPENAI_API_KEY がないため、AIによるsheet_name自動設計はスキップします。")
        else:
            try:
                # 既存レイアウトが無い/または新規resource_type（またはデフォルトのまま）を対象にする
                all_types_in_tf = sorted({(r.get("type") or "").strip() for r in resources if (r.get("type") or "").strip()})
                sheet_suggestions = suggest_sheets_with_ai(all_types_in_tf, model=model)
                # sheet_suggestions[rt] = {"group_key": "...", "aws_console_name": "..."}

                # group_key -> resource_types
                group_map: dict[str, list[str]] = {}
                for rt, meta in sheet_suggestions.items():
                    gk = (meta.get("group_key") or "").strip()
                    if not gk:
                        continue
                    group_map.setdefault(gk, []).append(rt)

                # group_key -> primary_resource_type を決め、primaryのaws_console_nameをsheet_nameにする
                group_sheet_name: dict[str, str] = {}
                for gk, rts in group_map.items():
                    primary_rt = pick_primary_resource_type(rts, type_counts)
                    primary_name = (sheet_suggestions.get(primary_rt, {}).get("aws_console_name") or primary_rt).strip()
                    group_sheet_name[gk] = primary_name

                    if verbose:
                        counts = {rt: type_counts.get(rt, 0) for rt in rts}
                        print(
                            "[VERBOSE] sheet_group:", gk,
                            "primary:", primary_rt,
                            "count:", type_counts.get(primary_rt, 0),
                            "candidates:", rts,
                            "counts:", counts,
                        )

                # rowへ適用（既存カスタムを壊しにくくする）
                for row in rows:
                    rt = (row.get("resource_type") or "").strip()
                    if not rt:
                        continue

                    meta = sheet_suggestions.get(rt)
                    if not meta:
                        continue

                    gk = (meta.get("group_key") or "").strip()
                    if not gk:
                        continue

                    target_sheet = group_sheet_name.get(gk)
                    if not target_sheet:
                        continue

                    # 既存CSVを尊重:
                    # - 新規行は上書きOK
                    # - 既存行でも、sheet_nameがresource_typeそのまま(=デフォルト臭い)なら上書きOK
                    is_new = bool(row.get("_is_new"))
                    current_sheet = (row.get("sheet_name") or "").strip()
                    if is_new or (current_sheet == rt):
                        row["sheet_name"] = target_sheet

            except Exception as e:
                print("[WARN] AIによるsheet_name自動設計に失敗したため、そのまま出力します:", e)

    # ★ AI で header を調整（新規行だけ候補を作る）
    if use_ai_header and new_rows_for_ai:
        if "OPENAI_API_KEY" not in os.environ:
            print("[WARN] OPENAI_API_KEY がないため、AIによるheader調整はスキップします。")
        else:
            try:
                header_suggestions = suggest_headers_with_ai(new_rows_for_ai, model=model)
                # header_suggestions: { (resource_type, attribute_path): "新しいヘッダー名" }

                for row in rows:
                    key = (row.get("resource_type", ""), row.get("attribute_path", ""))
                    new_header = header_suggestions.get(key)
                    if new_header:
                        row["header"] = new_header

            except Exception as e:
                print(
                    "[WARN] AIによるheader調整に失敗したため、そのまま出力します:",
                    e,
                )

    # ★ AI で order を自動採番
    try:
        # resource_type ごとに行をグルーピング
        by_type: dict[str, list[dict]] = {}
        for row in rows:
            resource_type = row.get("resource_type") or ""
            by_type.setdefault(resource_type, []).append(row)

        # 旧CSVに存在していた resource_type の集合
        prev_types = {key[0] for key in prev_layout_map.keys()} if prev_layout_map else set()

        order_targets: dict[str, list[dict]] = {}
        for resource_type, type_rows in by_type.items():
            if not resource_type:
                continue

            needs_update = False
            if not prev_layout_map or resource_type not in prev_types:
                needs_update = True
            elif any(row.get("_is_new") for row in type_rows):
                needs_update = True

            if needs_update:
                order_targets[resource_type] = type_rows

        ai_order_map: dict[tuple[str, str], int] = {}
        order_response_valid = False
        if not order_targets:
            pass
        elif "OPENAI_API_KEY" not in os.environ:
            print("[WARN] OPENAI_API_KEY がないため、AIによるorder自動採番はスキップします。")
        else:
            try:
                ai_order_map = suggest_orders_with_ai(order_targets, model=model)
                order_response_valid = True
            except Exception as e:
                print("[WARN] AIによるorder採番に失敗したため、既存orderを維持します:", e)
                ai_order_map = {}

        if order_response_valid:
            for resource_type, type_rows in order_targets.items():
                applied = False

                for row in type_rows:
                    attribute_path = row.get("attribute_path") or ""
                    mapped = ai_order_map.get((resource_type, attribute_path))
                    if mapped is None:
                        continue
                    row["order"] = str(mapped)
                    applied = True

                if all(not (row.get("order") or "").strip() for row in type_rows):
                    for idx, row in enumerate(type_rows, start=1):
                        row["order"] = str(idx)

                # ★ 最終的に、order が空の列を含めて 1..N の連番に整える
                renumber_orders_for_type(type_rows)

    except Exception as e:
        print(
            "[WARN] AIによるorder自動採番処理で例外が発生したため、既存orderをそのまま出力します:",
            e,
        )

    # CSVを書き出し
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        fieldnames = [
            "resource_type",
            "attribute_path",
            "sheet_name",
            "header",
            "required",
            "order",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            writer.writerow(
                {
                    "resource_type": row.get("resource_type", ""),
                    "attribute_path": row.get("attribute_path", ""),
                    "sheet_name": row.get("sheet_name", ""),
                    "header": row.get("header", ""),
                    "required": (row.get("required") or "").strip(),
                    "order": row.get("order", ""),
                }
            )

    return csv_path

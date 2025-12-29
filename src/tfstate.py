from __future__ import annotations

import json
from pathlib import Path


# ============================================================
# 入力 JSON 読み込み
# ============================================================

def load_tf_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# terraform show -json (state) からリソース抽出
# ============================================================

def _extract_resources_from_state(tf_json: dict):
    """terraform show -json （state系）の values.root_module からリソース一覧を抽出"""
    resources = []
    values = tf_json.get("values")
    if not isinstance(values, dict):
        return resources

    root_module = values.get("root_module")
    if not isinstance(root_module, dict):
        return resources

    def walk_module(mod: dict):
        for res in mod.get("resources", []):
            if not isinstance(res, dict):
                continue
            resources.append(
                {
                    "address": res.get("address"),
                    "type": res.get("type"),
                    "values": res.get("values") or {},
                }
            )
        for child in mod.get("child_modules", []):
            if isinstance(child, dict):
                walk_module(child)

    walk_module(root_module)
    return resources


def extract_resources(tf_json: dict):
    """terraform show -json （state形式）の tf.json からリソース一覧を抽出する"""
    resources = _extract_resources_from_state(tf_json)
    if not resources:
        # values.root_module.resource が取れない = show -json じゃない可能性が高い
        raise ValueError(
            "tf.json からリソースを取得できませんでした。\n"
            "terraform show -json の出力ファイルかどうかを確認してください。"
        )
    return resources


# ============================================================
# attribute_path / 値集計（analyze用）
# ============================================================

def _iter_attribute_paths(prefix: str, value):
    """values以下の辞書から属性パスを列挙する（ドット区切り）"""
    if isinstance(value, dict):
        for k, v in value.items():
            new_prefix = f"{prefix}.{k}" if prefix else k
            yield from _iter_attribute_paths(new_prefix, v)
    elif isinstance(value, list):
        # リストについては、ひとまずプロパティ名までを1列として扱う（詳細な中身はAIに任せる）
        if prefix:
            yield prefix
    else:
        if prefix:
            yield prefix


def _is_effective_value(v) -> bool:
    """
    tf.json 内の「値」が「設定されている」とみなせるかを判定する。
    - null, "", [], {} は「未設定」
    - それ以外は「設定あり」
    """
    if v is None:
        return False
    if v == "":
        return False
    if isinstance(v, (list, dict)) and not v:
        return False
    return True


def _collect_attr_values(prefix: str, value, result: dict[str, list]):
    """
    values ツリーを走査して、
    attribute_path -> [値, 値, ...] という形で集計するヘルパー。
    """
    if isinstance(value, dict):
        for k, v in value.items():
            new_prefix = f"{prefix}.{k}" if prefix else k
            _collect_attr_values(new_prefix, v, result)
    elif isinstance(value, list):
        # list 自体を1つの「値」として扱う（中身までは展開しない）
        if prefix:
            result.setdefault(prefix, []).append(value)
    else:
        if prefix:
            result.setdefault(prefix, []).append(value)

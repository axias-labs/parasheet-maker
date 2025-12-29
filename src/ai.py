from openai import OpenAI

import json

def suggest_headers_with_ai(rows: list[dict], model: str = "gpt-4.1-mini") -> dict[tuple[str, str], str]:
    """
    rows: {"resource_type", "attribute_path", "header"} を含むdictのリスト（新規行だけ）
    戻り値: {(resource_type, attribute_path): header} の辞書
    """
    client = OpenAI()

    # AIに渡す用にシンプルな構造にする
    payload = [
        {
            "resource_type": r["resource_type"],
            "attribute_path": r["attribute_path"],
            "current_header": r.get("header", ""),
        }
        for r in rows
    ]

    system_prompt = (
        "あなたはAWSマネジメントコンソールのUI文言に詳しいクラウドエンジニアです。\n"
        "与えられた resource_type と attribute_path から、パラメータシート用の列ヘッダー名を決めてください。\n"
        "\n"
        "要件:\n"
        "- 可能な限り、AWSマネジメントコンソール(日本語)で使われている名称に合わせてください。\n"
        "- 適切な日本語名称が思い当たらない場合は、attribute_path の末尾をそのまま使って構いません。\n"
        "- 同じ resource_type + attribute_path の組み合わせについては、毎回同じheader名を返してください。\n"
        "- header名はできるだけ簡潔にしてください（例: 'CIDRブロック', 'アベイラビリティーゾーン' など）。\n"
        "- 出力は JSON の配列のみとし、各要素は\n"
        '  { "resource_type": "...", "attribute_path": "...", "header": "..." }\n'
        "  という形式にしてください。余計なテキストは一切出力しないでください。\n"
    )

    user_prompt = json.dumps(payload, ensure_ascii=False)

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
    )

    content = resp.choices[0].message.content or "[]"
    try:
        result_list = json.loads(content)
    except Exception:
        # もしパースに失敗したら何も変更しない
        return {}

    suggestions: dict[tuple[str, str], str] = {}
    for item in result_list:
        try:
            resource_type = item.get("resource_type")
            attribute_path = item.get("attribute_path")
            header = item.get("header")
        except AttributeError:
            continue
        if not resource_type or not attribute_path or not header:
            continue
        suggestions[(resource_type, attribute_path)] = header
    return suggestions


def suggest_orders_with_ai(
    grouped_rows: dict[str, list[dict]],
    model: str = "gpt-4.1-mini",
) -> dict[tuple[str, str], int]:
    """
    複数 resource_type 分の attribute_path をまとめて AI に渡し、order を決めてもらう。

    grouped_rows: { resource_type: [ layout行(dict), ... ] }
    戻り値: { (resource_type, attribute_path): order(int) }
    """
    if not grouped_rows:
        return {}

    client = OpenAI()

    payload = []
    for resource_type, rows in grouped_rows.items():
        cols = []
        for r in rows:
            cols.append(
                {
                    "attribute_path": r.get("attribute_path", ""),
                    "header": r.get("header", ""),
                    "required": r.get("required", ""),
                    "link_to_parent_attr": r.get("link_to_parent_attr", ""),
                }
            )
        payload.append(
            {
                "resource_type": resource_type,
                "columns": cols,
            }
        )

    system_prompt = (
        "あなたはAWSインフラに詳しいクラウドエンジニアです。\n"
        "これから Terraform の複数 resource_type ごとの属性一覧が渡されます。\n"
        "各 resource_type についてパラメータシートの列順(order)を決めてください。\n"
        "\n"
        "ルール:\n"
        "- 1番目は、ID や 名前 など、そのリソースを特定するためのキー項目にしてください。\n"
        "- 可能であれば ARN 以外のID/名前系を1番目にしてください。ID/名前系が無い場合のみ ARN を1番目にして構いません。\n"
        "- 2番目以降は「基本的な設定項目」「運用レビューやセキュリティレビューでよく確認するもの」を優先し、\n"
        "  その他の詳細設定は後ろにしてください。\n"
        "- order は 1 から始まる整数の連番にしてください（1,2,3,...）。\n"
        "- 入力に含まれているすべての attribute_path について、必ず order を割り当ててください。\n"
        "- 出力は JSON 配列のみとし、各要素は\n"
        '  { "resource_type": "...", "orders": [ { "attribute_path": "...", "order": 1 }, ... ] }\n'
        "  という形式にしてください。余計なテキストは一切出力しないでください。\n"
    )

    user_prompt = json.dumps(payload, ensure_ascii=False)

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
    )

    content = resp.choices[0].message.content or "[]"
    try:
        result_list = json.loads(content)
    except Exception:
        return {}

    order_map: dict[tuple[str, str], int] = {}
    for item in result_list:
        if not isinstance(item, dict):
            continue
        resource_type = (item.get("resource_type") or "").strip()
        orders = item.get("orders")
        if not resource_type or not isinstance(orders, list):
            continue
        for order_item in orders:
            if not isinstance(order_item, dict):
                continue
            attribute_path = (order_item.get("attribute_path") or "").strip()
            if not attribute_path:
                continue
            order_val = order_item.get("order")
            try:
                order_int = int(order_val)
            except Exception:
                continue
            order_map[(resource_type, attribute_path)] = order_int

    return order_map


def suggest_sheets_with_ai(resource_types: list[str], model: str = "gpt-4.1-mini") -> dict[str, dict]:
    """
    入力: resource_types (例: ["aws_vpc", "aws_subnet", ...])
    出力: {
      "aws_vpc": {"group_key": "network_vpc", "aws_console_name": "VPC"},
      ...
    }
    """
    client = OpenAI()

    payload = [{"resource_type": rt} for rt in sorted(set(resource_types)) if rt]

    system_prompt = (
        "あなたはAWSマネジメントコンソールの画面構成とTerraformのresource_typeに詳しいクラウドエンジニアです。\n"
        "これから Terraform の resource_type 一覧が渡されます。\n"
        "目的はパラメータシート(layout_template.csv)の sheet_name を自動設計することです。\n"
        "\n"
        "要件:\n"
        "- 関連が強い resource_type は同一シートにまとめてください（例: VPC/サブネット/ルートテーブル/IGW/NATGW など）。\n"
        "- 各 resource_type について、次の2つを決めてください:\n"
        "  1) group_key: 同一シートにまとめるためのグループ識別子（英数字とアンダースコア。例: network_vpc）\n"
        "  2) aws_console_name: AWSマネジメントコンソール(日本語UI)での代表的なリソース名称（短く。例: VPC, サブネット, セキュリティグループ）\n"
        "- group_key は、同じ系統なら必ず同じ値になるよう一貫性を保ってください。\n"
        "- 出力は JSON 配列のみ。\n"
        '  形式: { "resource_type": "...", "group_key": "...", "aws_console_name": "..." }\n'
        "  余計なテキストは一切出力しないでください。\n"
    )

    user_prompt = json.dumps(payload, ensure_ascii=False)

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
    )

    content = resp.choices[0].message.content or "[]"
    try:
        result_list = json.loads(content)
    except Exception:
        return {}

    out: dict[str, dict] = {}
    for item in result_list:
        if not isinstance(item, dict):
            continue
        rt = (item.get("resource_type") or "").strip()
        gk = (item.get("group_key") or "").strip()
        nm = (item.get("aws_console_name") or "").strip()
        if not rt or not gk or not nm:
            continue
        out[rt] = {"group_key": gk, "aws_console_name": nm}
    return out
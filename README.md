# ParaSheet Maker (パラシメーカー)
Terraform の `terraform show -json`（state）を解析し、<br>
**クラウドエンジニア向けのパラメータシート（Markdown / Excel）を自動生成する CLI ツールです。**

Terraform や state を直接読めないメンバーでも、<br>
**AWS リソースの設定内容を一覧で把握・レビューできる**ことを目的としています。

---

## 特徴
- Terraform state（`terraform show -json`）を入力として利用
- layout_template.csv によるレイアウト完全制御
- Markdown → Excel の 2段階生成で以下を両立
  - MarkdownによるGit差分管理
  - 現場で使えるExcel出力
- generate モードでは AI を使わず、安定した出力を保証
- analyze モードでは AI を使った以下の補助（任意）
  - 列ヘッダ名の提案
  - シート構成の自動設計
  - 列順（order）の初期提案

---

## 想定ユースケース

- Terraform で管理している AWS 環境の設定棚卸し
- 運用・監査・レビュー用のパラメータシート作成
- Terraform を触らないメンバー向けの設定共有
- 将来的な「差分パラシ」や変更管理の土台

---

## インストール
```
git clone https://github.com/axias-labs/parasheet-maker.git
cd parasheet-maker
pip install -r requirements.txt
```
※ Python 3.10+ を推奨

---

## 使い方
### 1. Terraform state を JSON で出力
```
terraform show -json > tf.json
```

### 2. analyze モード（レイアウト CSV 生成）
```
python parasheet_maker.py tf.json --mode analyze
```
`layout_template.csv` が生成されます。初回はこのCSVを編集します。<br>
編集内容は以下をご確認ください。

#### layout_template.csvの項目と編集箇所

| 項目           | 内容                                                                                                                                              | 編集可否 | AI利用可否 | 
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | -------- | ---------- | 
| resource_type  | terraformのリソースタイプ                                                                                                                         | ×        | ×          | 
| attribute_path | resource_typeに紐づくパラメータ                                                                                                                   | ×        | ×          | 
| sheet_name     | Excel出力時のシート名称。AI未使用時、resource_typeがデフォルト値。異なるresource_typeを同じsheet_nameにすることで同一シートにまとめることが可能。 | ⚪︎     | ⚪︎       | 
| header         | Markdown/Excel出力時の表のヘッダー名。AI未使用時、attribute_pathがデフォルト値。                                                                  | ⚪︎     | ⚪︎       | 
| required       | Markdown/Excel出力時の列表示ON/OFF。ON=1、OFF=空欄。デフォルトはtf.jsonに値がある＝ON、値が無い＝OFF。                                            | ⚪︎     | ×          | 
| order          | Markdown/Excel出力時の列表示順。                                                                                                                  | ⚪︎     | ⚪︎       | 

#### AI 補助を使う場合（任意）

AI補助を使用してlayout_template.csvを生成する場合は、以下を実施します。

1. OpenAI APIを使用できる環境とする
2. 以下のコマンドを実施
```
export OPENAI_API_KEY=your_api_key

python parasheet_maker.py tf.json \
  --mode analyze \
  --ai-header \
  --ai-sheet
```

##### オプション説明
- ai-header：layout_templateのheaderをわかりやすい値に変換
- ai-sheet：layout_templateのsheet_nameをわかりやすい値に変換。関連するresource_typeは同一シートにグルーピング。

### 3. generate モード（Markdown + Excel 生成）

layout_template.csvを出力(&編集)したら、以下のコマンドを実施します。<br>
※layout_template.csvが存在しない場合は、上記「2. analyze モード（レイアウト CSV 生成）」を実行してください。

```
python parasheet_maker.py tf.json --mode generate
```

Markdown/Excelファイルが出力されます。

---

## 出力イメージ

- Markdown（Git管理用）
- Excel（レビュー・運用用）

※ サンプル出力は examples/ を参照してください

---

## 設計思想
- 出力の再現性・安定性を最優先
- 表構造・値抽出・Markdown 生成は すべて Python ロジック
- Terraform/AWSのアップデートへの追随は極力AIに任せる

「ゆらぎが発生するため、AIで全部を作らない」ことを前提に設計しています。<br>
プログラムで一定した品質を保ち、AIで各サービスのアップデートに追随しやすく利便性・運用性の良いツールを目指します。

---

## 今後のリリースでの対応予定
- 前回パラシとの差分抽出
- レビュー向け注釈・説明文生成
- SaaS化

---

## ライセンス
MIT License

---

## Feedback
ParaSheet Maker を使ってみた感想やバグ報告・改善提案大歓迎です。

- 感想：Discussions
- バグ報告・改善提案：GitHub Issues

---

## Maintainer

ParaSheet Maker は、小規模な独立法人 AXIAS によってメンテナンスされています。
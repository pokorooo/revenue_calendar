# 収益カレンダー

株の収益をカレンダーで確認できるアプリです。現在はStreamlit版のみ提供しています。

- ローカル実行: `pip install -r requirements.txt && streamlit run app.py`
- 表示: streamlit_calendar による月カレンダー（日本語・日曜始まり）

## CSVフォーマット（FIFO損益計算）

```
date,symbol,side,quantity,price
2024-01-05,7203,BUY,100,2400
2024-01-10,7203,SELL,100,2500
```

- `side`: BUY または SELL（大小文字は自動で解釈）
- 数量・価格は数値（カンマ含んでもOK）
- 空売りは未対応（保有数量を超える売却は未マッチ分をスキップして警告表示）

## データ保存

- セッション内で選択日などの状態を保持します。

## デプロイ（Streamlit Community Cloud）

1. 本リポジトリをGitHubにプッシュ
2. https://share.streamlit.io にサインイン → New app
3. リポジトリ/ブランチを選択し、Main file path に `app.py` を指定
4. 依存は `requirements.txt` を自動で解決（本リポジトリに同梱）
5. Deploy を押すだけで起動します

注意:
- 上場銘柄リスト（`data/jpx_symbols.csv`）はアプリ内の「銘柄リスト（上場企業）」から更新できます。
- Streamlit Community Cloudではファイルは永続化されないことがあります。リストが見当たらない場合は、起動後に「更新」またはCSV取込で補完してください。

## よくある操作

- 月移動: 前月/今日/翌月ボタン
- サンプルCSV: 画面のボタンからダウンロード
- 手入力: 日付を選択して金額・メモを追加/削除

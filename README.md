# 投稿マシン(v1)


MyGPTs等で生成した**タイトル/本文**を貼り付けて、各プラットフォームに**素早く投稿**するための手作業支援アプリ。生成API・スプレッドシート連携は**不使用**。


## 構成

. ├── platform_clients.py ├── streamlit_app.py ├── utils.py ├── requirements.txt ├── .gitignore └── .streamlit/ └── secrets.example.toml

## セットアップ（ローカル）
```bash
python -m venv .venv
. .venv/bin/activate # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .streamlit/secrets.example.toml .streamlit/secrets.toml
# secrets.toml を編集（[wp_configs] を必ず設定）
streamlit run streamlit_app.py

デプロイ（Streamlit Cloud）

本リポジトリをGitHubへPush（新規アカウントでOK）

Streamlit Cloudで本リポを指定してデプロイ

App secrets に .streamlit/secrets.example.toml の内容を参考に設定（特に [wp_configs]）

WordPress 設定のポイント

アプリケーションパスワードを発行して username/app_password を使用

Xserverの403回避策として、まず ?rest_route=/wp/v2/... で試行し、失敗時は /wp-json/wp/v2/... にフォールバック

予約投稿: 予約日時を入れると status=future + date_gmt で投稿。即時なら空でOK

アイキャッチ: JPEG/PNGをアップロード→featured_media に自動セット

非WP（Seesaa/FC2/Blogger/Livedoor）

現状は半自動（HTML一括出力・ダウンロード）で実運用を優先

将来API化する場合は platform_clients.py にクライアントを実装し、タブ側で置換

よくある質問

URLが出ない → 投稿成功時に link を表示。テーマや権限で空の場合は guid.rendered を併記

403が出る → Xserverの国外IP制限/WAF/リファラ制限を確認。?rest_route= で通ることが多い

カテゴリIDが不明 → WP管理画面の「投稿＞カテゴリ」でIDを確認（URL末尾の tag_ID=）

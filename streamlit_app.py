# ------------------------------------------------------------
# streamlit_app.py — 投稿マシン 完全版
# ・WordPress: REST(?rest_route=) / 予約投稿(JST→UTC) / アイキャッチ / カテゴリ名プルダウン
# ・Seesaa/FC2: XML-RPC 自動投稿（publish/draft）
# ・Blogger: Google API 自動投稿（Service Account）
# ・Livedoor: Cookieログイン + フォームPOST 自動投稿（confirm/final両対応）
# ・複数アカウント切替（Secretsに定義）
# ------------------------------------------------------------
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

import streamlit as st
from PIL import Image
import requests
import re
import unicodedata
import io
import xmlrpc.client
from bs4 import BeautifulSoup

# Blogger 用（未インストールでも起動できるように）
try:
    from googleapiclient.discovery import build
    from google.oauth2 import service_account
    HAS_GOOGLE = True
except Exception:
    HAS_GOOGLE = False


# =========================
# ユーティリティ
# =========================
def to_slug(text: str, max_len: int = 80) -> str:
    s = unicodedata.normalize("NFKC", text or "").lower()
    s = re.sub(r"[^a-z0-9\\s-]", "", s)
    s = re.sub(r"[\\s-]+", "-", s).strip("-")
    return (s[:max_len] or "post")

def ensure_html_blocks(html: str) -> str:
    s = (html or "").strip()
    if not s:
        return ""
    lowered = s.lower()
    if ("<p>" not in lowered) and ("<h" not in lowered) and ("<ul" not in lowered) and ("<ol" not in lowered):
        s = "\\n".join(f"<p>{line}</p>" for line in s.splitlines() if line.strip())
    return s

def jst_to_utc_iso(local_dt: datetime) -> str:
    utc_dt = local_dt - timedelta(hours=9)  # JST→UTC
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S")

def _kv_list_to_dict(kv_list: List[str]) -> Dict[str, str]:
    out = {}
    for line in kv_list or []:
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


# =========================
# WordPress クライアント
# =========================
class WordPressClient:
    def __init__(self, base_url: str, username: str, app_password: str):
        self.base = (base_url or "").rstrip("/")
        self.auth = (username, app_password)

    def _endpoints(self, path: str) -> List[str]:
        return [
            f"{self.base}/?rest_route=/wp/v2{path}",
            f"{self.base}/wp-json/wp/v2{path}",
        ]

    def _request_first_ok(self, method: str, path: str, **kwargs) -> requests.Response:
        last_err: Optional[Exception] = None
        for url in self._endpoints(path):
            try:
                r = requests.request(method, url, auth=self.auth, timeout=30, **kwargs)
                if 200 <= r.status_code < 300:
                    return r
                last_err = Exception(f"{r.status_code}: {r.text[:300]}")
            except requests.RequestException as e:
                last_err = e
        raise last_err or Exception("WordPress request failed")

    def upload_media(self, image: Image.Image, filename: str = "eyecatch.jpg") -> int:
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=85, optimize=True, progressive=True)
        buf.seek(0)
        headers = {
            "Content-Disposition": f"attachment; filename={filename}",
            "Content-Type": "image/jpeg",
        }
        r = self._request_first_ok("POST", "/media", headers=headers, data=buf.getvalue())
        return int(r.json().get("id"))

    def create_post(
        self,
        *,
        title: str,
        content_html: str,
        status: str = "draft",
        categories: Optional[List[int]] = None,
        featured_media: Optional[int] = None,
        slug: Optional[str] = None,
        date_gmt_iso: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "title": title,
            "content": content_html,
            "status": status,
        }
        if categories:
            payload["categories"] = categories
        if featured_media:
            payload["featured_media"] = featured_media
        if slug:
            payload["slug"] = slug
        if date_gmt_iso:
            payload["date_gmt"] = date_gmt_iso
            payload["status"] = "future"
        r = self._request_first_ok("POST", "/posts", json=payload)
        return r.json()


# =========================
# Streamlit ベース
# =========================
st.set_page_config(page_title="投稿マシン", layout="wide")
st.title("📤 投稿マシン — 完全版")

# Secrets 読み込み
WP_CONFIGS: Dict[str, Any] = st.secrets.get("wp_configs", {})
SEESAA_ACCOUNTS: Dict[str, Any] = st.secrets.get("seesaa_accounts", {})
FC2_ACCOUNTS: Dict[str, Any] = st.secrets.get("fc2_accounts", {})
BLOGGER_ACCOUNTS: Dict[str, Any] = st.secrets.get("blogger_accounts", {})
LIVEDOOR_ACCOUNTS: Dict[str, Any] = st.secrets.get("livedoor_accounts", {})
GOOGLE_SA: Dict[str, Any] = dict(st.secrets.get("google_service_account", {}))

def article_form(key_prefix: str) -> Dict[str, Any]:
    c1, c2 = st.columns([3, 2])
    with c1:
        title = st.text_input("タイトル", key=f"{key_prefix}_title")
        slug_custom = st.text_input("スラグ（任意）", key=f"{key_prefix}_slug")
        body = st.text_area("本文（HTML / プレーン）", height=320, key=f"{key_prefix}_body")
    with c2:
        st.caption("改行テキストは自動で <p> に変換します。画像は本文内に挿入してください。")
    return {"title": title, "slug": slug_custom, "body": body}


# =========================
# WordPress タブ
# =========================
def tab_wordpress():
    st.subheader("WordPress 投稿")

    if not WP_CONFIGS:
        st.warning("`.streamlit/secrets.toml` に [wp_configs] を設定してください。")
        return

    # 表示名: 「label / キー名」
    display_map = {k: f"{v.get('label','')}".strip()+" / "+k for k, v in WP_CONFIGS.items()}
    site_key = st.selectbox("アカウント選択", list(display_map.keys()), format_func=lambda k: display_map[k], key="wp_site")
    cfg = WP_CONFIGS.get(site_key, {})

    data = article_form("wp")

    col1, col2, col3 = st.columns([1.5, 1.5, 2])
    with col1:
        categories_map = cfg.get("categories", {}) or {}
        cat_id = None
        if categories_map:
            cat_name = st.selectbox("カテゴリ", ["（未選択）"] + list(categories_map.keys()), key="wp_cat_name")
            if cat_name != "（未選択）":
                cat_id = categories_map[cat_name]
    with col2:
        sched_toggle = st.checkbox("予約投稿する", key="wp_sched_toggle")
        if sched_toggle:
            sched_date = st.date_input("予約日", key="wp_date")
            sched_time = st.time_input("予約時刻", key="wp_time")
        else:
            sched_date = None
            sched_time = None
    with col3:
        eyecatch_file = st.file_uploader("アイキャッチ（JPEG/PNG）", type=["jpg", "jpeg", "png"], key="wp_eye")

    status_choice = st.selectbox("公開状態", ["draft（下書き）", "publish（即時公開）"], key="wp_status")

    if st.button("WordPressへ投稿", type="primary", key="wp_submit"):
        try:
            base_url = cfg.get("url", "")
            username = cfg.get("user", "")
            app_password = cfg.get("password", "")
            if not base_url or not username or not app_password:
                st.error("url / user / password が未設定です。")
                return

            slug_mode = (cfg.get("slug_mode") or "").lower().strip()
            slug_input = (data["slug"] or "").strip()
            if slug_input:
                slug_final = slug_input
            else:
                slug_final = to_slug(data["title"]) if slug_mode == "auto" else None

            content_html = ensure_html_blocks(data["body"])

            # 予約
            date_gmt_iso = None
            status = "draft" if status_choice.startswith("draft") else "publish"
            if sched_toggle and sched_date and sched_time:
                naive_local = datetime.combine(sched_date, sched_time)
                date_gmt_iso = jst_to_utc_iso(naive_local)
                status = "future"

            # アイキャッチ
            client = WordPressClient(base_url, username, app_password)
            media_id = None
            if eyecatch_file:
                img = Image.open(eyecatch_file).convert("RGB")
                media_id = client.upload_media(img, "eyecatch.jpg")

            cats = [cat_id] if cat_id else None
            res = client.create_post(
                title=data["title"],
                content_html=content_html,
                status=status,
                categories=cats,
                featured_media=media_id,
                slug=slug_final,
                date_gmt_iso=date_gmt_iso,
            )
            link = res.get("link") or (res.get("guid") or {}).get("rendered")
            st.success("投稿に成功しました。")
            st.json({"id": res.get("id"), "status": res.get("status"), "link": link})
            if link:
                st.markdown(f"**URL**: {link}")
        except Exception as e:
            st.error(f"投稿失敗: {e}")


# =========================
# Seesaa / FC2（XML-RPC）
# =========================
def _xmlrpc_post(cfg: Dict[str, Any], title: str, html: str, publish: bool) -> str:
    server = xmlrpc.client.ServerProxy(cfg["endpoint"])
    post = {"title": title, "description": html}
    post_id = server.metaWeblog.newPost(cfg["blog_id"], cfg["username"], cfg["password"], post, bool(publish))
    return str(post_id)

def _account_select_display(accounts: Dict[str, Any], key_prefix: str) -> str:
    # 表示名: 「label / キー名」
    return st.selectbox(
        "アカウント選択",
        list(accounts.keys()),
        format_func=lambda k: f"{accounts[k].get('label','')} / {k}".strip(" /"),
        key=f"{key_prefix}_acc"
    )

def tab_seesaa():
    st.subheader("Seesaa 投稿")
    if not SEESAA_ACCOUNTS:
        st.warning("secrets に [seesaa_accounts] を設定してください。")
        return
    acc = _account_select_display(SEESAA_ACCOUNTS, "seesaa")
    cfg = SEESAA_ACCOUNTS[acc]
    data = article_form("seesaa")
    is_publish = st.selectbox("公開状態", ["publish（公開）", "draft（下書き）"], key="seesaa_mode").startswith("publish")
    if st.button("Seesaaへ投稿", key="seesaa_submit"):
        try:
            post_id = _xmlrpc_post(cfg, data["title"], ensure_html_blocks(data["body"]), is_publish)
            st.success(f"投稿成功 ID: {post_id}")
        except Exception as e:
            st.error(f"投稿失敗: {e}")

def tab_fc2():
    st.subheader("FC2 投稿")
    if not FC2_ACCOUNTS:
        st.warning("secrets に [fc2_accounts] を設定してください。")
        return
    acc = _account_select_display(FC2_ACCOUNTS, "fc2")
    cfg = FC2_ACCOUNTS[acc]
    data = article_form("fc2")
    is_publish = st.selectbox("公開状態", ["publish（公開）", "draft（下書き）"], key="fc2_mode").startswith("publish")
    if st.button("FC2へ投稿", key="fc2_submit"):
        try:
            post_id = _xmlrpc_post(cfg, data["title"], ensure_html_blocks(data["body"]), is_publish)
            st.success(f"投稿成功 ID: {post_id}")
        except Exception as e:
            st.error(f"投稿失敗: {e}")


# =========================
# Blogger（Google API）
# =========================
def tab_blogger():
    st.subheader("Blogger 投稿")
    if not HAS_GOOGLE:
        st.warning("Blogger投稿には google-api-python-client 等の依存が必要です。requirements.txt を反映してください。")
        return
    if not BLOGGER_ACCOUNTS:
        st.warning("secrets に [blogger_accounts] を設定してください。")
        return
    if not GOOGLE_SA:
        st.warning("secrets に [google_service_account] を設定してください。")
        return

    acc = _account_select_display(BLOGGER_ACCOUNTS, "blogger")
    cfg = BLOGGER_ACCOUNTS[acc]
    data = article_form("blogger")
    is_publish = st.selectbox("公開状態", ["publish（公開）", "draft（下書き）"], key="blogger_mode").startswith("publish")

    if st.button("Bloggerへ投稿", key="blogger_submit"):
        try:
            SCOPES = ["https://www.googleapis.com/auth/blogger"]
            creds = service_account.Credentials.from_service_account_info(GOOGLE_SA, scopes=SCOPES)
            service = build("blogger", "v3", credentials=creds)

            body = {
                "kind": "blogger#post",
                "title": data["title"],
                "content": ensure_html_blocks(data["body"]),
            }
            post = service.posts().insert(blogId=cfg["blog_id"], body=body, isDraft=(not is_publish)).execute()
            st.success(f"投稿成功: {post.get('url')}")
        except Exception as e:
            st.error(f"投稿失敗: {e}")


# =========================
# Livedoor（Cookieログイン + POST）
# =========================
def livedoor_login_and_post(cfg: Dict[str, Any], title: str, html_content: str, publish: bool = True) -> Dict[str, Any]:
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})

    # 1) ログイン
    login_payload = {
        cfg.get("username_field", "livedoor_id"): cfg["username"],
        cfg.get("password_field", "password"):    cfg["password"],
    }
    r = s.post(cfg["login_url"], data=login_payload, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"Login failed: {r.status_code}")

    # 2) 新規投稿ページ → hidden/CSRF 抽出
    r = s.get(cfg["new_post_url"], timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"Open new post failed: {r.status_code}")
    soup = BeautifulSoup(r.text, "lxml")

    payload: Dict[str, str] = {}
    # 2-1) hidden の吸い上げ
    for inp in soup.select("input[type=hidden]"):
        name = inp.get("name")
        if not name:
            continue
        payload[name] = inp.get("value", "")

    # 2-2) CSRF
    csrf_sel = cfg.get("csrf_selector")
    csrf_field = cfg.get("csrf_field", "csrf_token")
    if csrf_sel:
        node = soup.select_one(csrf_sel)
        if not node:
            raise RuntimeError("CSRF token not found (selector mismatch)")
        payload[csrf_field] = node.get("value", "")

    # 3) 記事フィールド
    payload[cfg.get("title_field", "title")] = title
    payload[cfg.get("body_field", "body")]   = html_content

    # 3-1) 公開/下書き
    if publish and cfg.get("publish_field"):
        payload[cfg["publish_field"]] = cfg.get("publish_value", "1")
    if (not publish) and cfg.get("draft_field"):
        payload[cfg["draft_field"]] = cfg.get("draft_value", "1")

    # 3-2) 任意追加
    payload.update(_kv_list_to_dict(cfg.get("extra_kv", [])))

    # 4) POST（confirm → final の2段階に対応）
    if cfg.get("confirm_url") and cfg.get("final_submit_url"):
        r1 = s.post(cfg["confirm_url"], data=payload, timeout=30)
        if r1.status_code >= 400:
            raise RuntimeError(f"Confirm failed: {r1.status_code}")
        soup2 = BeautifulSoup(r1.text, "lxml")
        payload2: Dict[str, str] = {}
        for inp in soup2.select("input[type=hidden]"):
            name = inp.get("name")
            if not name:
                continue
            payload2[name] = inp.get("value", "")
        r2 = s.post(cfg["final_submit_url"], data=payload2, timeout=30)
        if r2.status_code >= 400:
            raise RuntimeError(f"Final submit failed: {r2.status_code}")
        return {"status": "ok", "code": r2.status_code}
    else:
        r = s.post(cfg["submit_url"], data=payload, timeout=30)
        if r.status_code >= 400:
            raise RuntimeError(f"Submit failed: {r.status_code}")
        return {"status": "ok", "code": r.status_code}

def tab_livedoor():
    st.subheader("Livedoor 投稿（Cookieログイン自動投稿）")
    if not LIVEDOOR_ACCOUNTS:
        st.warning("secrets に [livedoor_accounts] を設定してください。")
        return
    acc = _account_select_display(LIVEDOOR_ACCOUNTS, "livedoor")
    cfg = LIVEDOOR_ACCOUNTS[acc]
    data = article_form("livedoor")
    is_publish = st.selectbox("公開状態", ["publish（公開）", "draft（下書き）"], key="livedoor_mode").startswith("publish")
    if st.button("Livedoorへ投稿", type="primary", key="livedoor_submit"):
        try:
            html_out = ensure_html_blocks(data["body"])
            res = livedoor_login_and_post(cfg, data["title"], html_out, publish=is_publish)
            st.success(f"投稿成功: {res}")
        except Exception as e:
            st.error(f"投稿失敗: {e}")


# =========================
# レイアウト
# =========================
TAB_CONFIGS = [
    {"name": "WordPress", "fn": tab_wordpress},
    {"name": "Seesaa", "fn": tab_seesaa},
    {"name": "FC2", "fn": tab_fc2},
    {"name": "Blogger", "fn": tab_blogger},
    {"name": "Livedoor", "fn": tab_livedoor},
]
_tabs = st.tabs([t["name"] for t in TAB_CONFIGS])
for i, cfg in enumerate(TAB_CONFIGS):
    with _tabs[i]:
        cfg["fn"]()

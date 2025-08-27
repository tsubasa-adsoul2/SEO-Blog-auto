# ------------------------------------------------------------
# streamlit_app.py — 投稿マシン(v2) 完全版
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

# Blogger 用
from googleapiclient.discovery import build
from google.oauth2 import service_account

# =========================
# ユーティリティ
# =========================
def to_slug(text: str, max_len: int = 80) -> str:
    s = unicodedata.normalize("NFKC", text or "").lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"[\s-]+", "-", s).strip("-")
    return (s[:max_len] or "post")

def ensure_html_blocks(html: str) -> str:
    s = (html or "").strip()
    if not s:
        return ""
    lowered = s.lower()
    if ("<p>" not in lowered) and ("<h" not in lowered) and ("<ul" not in lowered) and ("<ol" not in lowered):
        s = "\n".join(f"<p>{line}</p>" for line in s.splitlines() if line.strip())
    return s

def jst_to_utc_iso(local_dt: datetime) -> str:
    utc_dt = local_dt - timedelta(hours=9)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S")

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
# Streamlit UI 共通フォーム
# =========================
def article_form(key_prefix: str = "") -> Dict[str, Any]:
    c1, c2 = st.columns([3, 2])
    with c1:
        title = st.text_input("タイトル", key=f"{key_prefix}_title")
        slug_custom = st.text_input("スラグ（任意）", key=f"{key_prefix}_slug")
        body = st.text_area("本文（HTML / プレーン）", height=320, key=f"{key_prefix}_body")
    with c2:
        st.caption("改行テキストは自動で <p> に変換します。画像は本文内に挿入してください。")
    return {"title": title, "slug": slug_custom, "body": body}

# =========================
# Secrets 読み込み
# =========================
WP_CONFIGS: Dict[str, Any] = st.secrets.get("wp_configs", {})
SEESAA_ACCOUNTS: Dict[str, Any] = st.secrets.get("seesaa_accounts", {})
FC2_ACCOUNTS: Dict[str, Any] = st.secrets.get("fc2_accounts", {})
BLOGGER_ACCOUNTS: Dict[str, Any] = st.secrets.get("blogger_accounts", {})
LIVEDOOR_ACCOUNTS: Dict[str, Any] = st.secrets.get("livedoor_accounts", {})

# =========================
# WordPress タブ
# =========================
def tab_wordpress():
    st.subheader("WordPress 投稿")
    sites = list(WP_CONFIGS.keys())
    site_key = st.selectbox("アカウント選択", sites, key="wp_site")
    cfg = WP_CONFIGS.get(site_key, {})

    data = article_form("wp")

    col1, col2, col3 = st.columns([1.5, 1.5, 2])
    with col1:
        categories_map = cfg.get("categories", {})
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
            sched_date = None; sched_time = None
    with col3:
        eyecatch_file = st.file_uploader("アイキャッチ", type=["jpg", "jpeg", "png"], key="wp_eye")

    if st.button("投稿する", type="primary", key="wp_submit"):
        try:
            client = WordPressClient(cfg["url"], cfg["user"], cfg["password"])
            slug_final = data["slug"].strip() or to_slug(data["title"])
            content_html = ensure_html_blocks(data["body"])
            date_gmt_iso = None; status = "draft"
            if sched_toggle and sched_date and sched_time:
                dt_local = datetime.combine(sched_date, sched_time)
                date_gmt_iso = jst_to_utc_iso(dt_local)
                status = "future"
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
            st.success(f"投稿成功: {res.get('link')}")
        except Exception as e:
            st.error(f"失敗: {e}")

# =========================
# Seesaa / FC2 XML-RPC
# =========================
def tab_seesaa():
    st.subheader("Seesaa 投稿")
    if not SEESAA_ACCOUNTS: st.warning("secretsに [seesaa_accounts] を設定してください。"); return
    acc = st.selectbox("アカウント選択", list(SEESAA_ACCOUNTS.keys()), key="seesaa_acc")
    cfg = SEESAA_ACCOUNTS[acc]
    data = article_form("seesaa")
    if st.button("Seesaaへ投稿", key="seesaa_submit"):
        try:
            server = xmlrpc.client.ServerProxy(cfg["endpoint"])
            post = {"title": data["title"], "description": ensure_html_blocks(data["body"])}
            post_id = server.metaWeblog.newPost(cfg["blog_id"], cfg["username"], cfg["password"], post, True)
            st.success(f"投稿成功 ID: {post_id}")
        except Exception as e:
            st.error(f"失敗: {e}")

def tab_fc2():
    st.subheader("FC2 投稿")
    if not FC2_ACCOUNTS: st.warning("secretsに [fc2_accounts] を設定してください。"); return
    acc = st.selectbox("アカウント選択", list(FC2_ACCOUNTS.keys()), key="fc2_acc")
    cfg = FC2_ACCOUNTS[acc]
    data = article_form("fc2")
    if st.button("FC2へ投稿", key="fc2_submit"):
        try:
            server = xmlrpc.client.ServerProxy(cfg["endpoint"])
            post = {"title": data["title"], "description": ensure_html_blocks(data["body"])}
            post_id = server.metaWeblog.newPost(cfg["blog_id"], cfg["username"], cfg["password"], post, True)
            st.success(f"投稿成功 ID: {post_id}")
        except Exception as e:
            st.error(f"失敗: {e}")

# =========================
# Blogger Google API
# =========================
def tab_blogger():
    st.subheader("Blogger 投稿")
    if not BLOGGER_ACCOUNTS: st.warning("secretsに [blogger_accounts] を設定してください。"); return
    acc = st.selectbox("アカウント選択", list(BLOGGER_ACCOUNTS.keys()), key="blogger_acc")
    cfg = BLOGGER_ACCOUNTS[acc]
    data = article_form("blogger")
    if st.button("Bloggerへ投稿", key="blogger_submit"):
        try:
            SCOPES = ["https://www.googleapis.com/auth/blogger"]
            creds = service_account.Credentials.from_service_account_info(dict(st.secrets["google_service_account"]), scopes=SCOPES)
            service = build("blogger", "v3", credentials=creds)
            body = {"kind": "blogger#post", "title": data["title"], "content": ensure_html_blocks(data["body"])}
            post = service.posts().insert(blogId=cfg["blog_id"], body=body, isDraft=False).execute()
            st.success(f"投稿成功: {post['url']}")
        except Exception as e:
            st.error(f"失敗: {e}")

# =========================
# Livedoor （未実装）
# =========================
def tab_livedoor():
    st.subheader("Livedoor 投稿（未実装）")
    st.info("公式APIがないため、将来的にCookieログイン方式で実装予定。現状は未対応です。")

# =========================
# レイアウト
# =========================
tabs = st.tabs(["WordPress", "Seesaa", "FC2", "Blogger", "Livedoor"])
with tabs[0]: tab_wordpress()
with tabs[1]: tab_seesaa()
with tabs[2]: tab_fc2()
with tabs[3]: tab_blogger()
with tabs[4]: tab_livedoor()

# ------------------------------------------------------------
# streamlit_app.py — 投稿マシン(v1) 完全版
# ・WordPress: ?rest_route= フォールバック / 予約投稿 / アイキャッチ対応
# ・カテゴリ選択: secrets.toml の categories をプルダウン表示
# ・予約投稿: JST入力 → UTC(-9h) に変換
# ・Seesaa / FC2 / Blogger / Livedoor: 半自動HTML出力
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

# =========================
# ユーティリティ
# =========================
def to_slug(text: str, max_len: int = 80) -> str:
    """簡易スラグ（半角英数とハイフンに規格化）"""
    s = unicodedata.normalize("NFKC", text or "").lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"[\s-]+", "-", s).strip("-")
    return (s[:max_len] or "post")

def ensure_html_blocks(html: str) -> str:
    """改行テキストを <p> でラップ"""
    s = (html or "").strip()
    if not s:
        return ""
    lowered = s.lower()
    if ("<p>" not in lowered) and ("<h" not in lowered) and ("<ul" not in lowered) and ("<ol" not in lowered):
        s = "\n".join(f"<p>{line}</p>" for line in s.splitlines() if line.strip())
    return s

def jst_to_utc_iso(local_dt: datetime) -> str:
    """JST naive datetime を UTC ISO文字列に変換"""
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
# Streamlit UI
# =========================
st.set_page_config(page_title="投稿マシン(v1)", layout="wide")
st.title("📤 投稿マシン(v1)")

# Secrets 読み込み
WP_CONFIGS: Dict[str, Dict[str, Any]] = st.secrets.get("wp_configs", {})

# --------------------
# 共通フォーム
# --------------------
def article_form(key_prefix: str = "") -> Dict[str, Any]:
    c1, c2 = st.columns([3, 2])
    with c1:
        title = st.text_input("タイトル", key=f"{key_prefix}_title")
        slug_custom = st.text_input("スラグ（任意：未入力なら自動）", key=f"{key_prefix}_slug")
        body = st.text_area("本文（HTML / プレーン）", height=320, key=f"{key_prefix}_body")
    with c2:
        st.caption("改行のみの本文は自動で `<p>` にラップされます。画像は本文内に挿入してください。")
    return {"title": title, "slug": slug_custom, "body": body}

# --------------------
# WordPressタブ
# --------------------
def tab_wordpress():
    st.subheader("WordPress 投稿（予約・アイキャッチ対応）")

    sites = list(WP_CONFIGS.keys())
    site_key = st.selectbox("投稿先アカウント", sites, key="wp_site")
    cfg = WP_CONFIGS.get(site_key, {})

    base_url = cfg.get("url", "")
    username = cfg.get("user", "")
    app_password = cfg.get("password", "")
    categories_map: Dict[str, int] = cfg.get("categories", {}) or {}

    # 入力
    data = article_form("wp")

    # カテゴリ選択
    col1, col2, col3 = st.columns([1.5, 1.5, 2])
    with col1:
        cat_id = None
        if categories_map:
            cat_name = st.selectbox("カテゴリ選択", ["（未選択）"] + list(categories_map.keys()), key="wp_cat_name")
            if cat_name != "（未選択）":
                cat_id = categories_map[cat_name]
    with col2:
        sched_toggle = st.checkbox("予約投稿する", value=False, key="wp_sched_toggle")
        if sched_toggle:
            sched_date = st.date_input("予約日", key="wp_date")
            sched_time = st.time_input("予約時刻", key="wp_time")
        else:
            sched_date = None
            sched_time = None
    with col3:
        eyecatch_file = st.file_uploader("アイキャッチ（JPEG/PNG）", type=["jpg", "jpeg", "png"], key="wp_eye")

    # 投稿ボタン
    if st.button("WordPressへ投稿", type="primary"):
        try:
            if not data["title"] or not data["body"]:
                st.warning("タイトルと本文は必須です。")
                return

            client = WordPressClient(base_url, username, app_password)
            content_html = ensure_html_blocks(data["body"])
            slug_final = data["slug"].strip() or to_slug(data["title"])

            # 予約日時
            date_gmt_iso = None
            status = "draft"
            if sched_toggle and sched_date and sched_time:
                naive_local = datetime.combine(sched_date, sched_time)
                date_gmt_iso = jst_to_utc_iso(naive_local)
                status = "future"

            # アイキャッチ
            media_id = None
            if eyecatch_file:
                img = Image.open(eyecatch_file).convert("RGB")
                media_id = client.upload_media(img, "eyecatch.jpg")

            # 投稿実行
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
            post_link = res.get("link") or (res.get("guid") or {}).get("rendered")
            st.success("投稿に成功しました。")
            st.json({"id": res.get("id"), "status": res.get("status"), "link": post_link})
            if post_link:
                st.markdown(f"**URL**: {post_link}")

        except Exception as e:
            st.error(f"投稿に失敗しました: {e}")

# --------------------
# 半自動（HTML出力）
# --------------------
def export_box(platform_name: str, key_prefix: str):
    st.caption(f"{platform_name}: 入力内容をコピペして投稿してください。")
    data = article_form(key_prefix)
    st.divider()
    html_out = ensure_html_blocks(data["body"])
    st.markdown("#### 出力プレビュー（HTML）")
    st.code(html_out, language="html")
    st.download_button(
        label="HTMLとして保存",
        data=html_out,
        file_name=f"{to_slug(data['title'] or 'post')}.html",
        mime="text/html",
        use_container_width=True,
        key=f"{key_prefix}_download"   # 👈 追加：タブごとにユニークID
    )

def tab_seesaa(): st.subheader("Seesaa（半自動）"); export_box("Seesaa", "seesaa")
def tab_fc2(): st.subheader("FC2（半自動）"); export_box("FC2", "fc2")
def tab_blogger(): st.subheader("Blogger（半自動）"); export_box("Blogger", "blogger")
def tab_livedoor(): st.subheader("Livedoor（半自動）"); export_box("Livedoor", "livedoor")

# --------------------
# レイアウト
# --------------------
_tabs = st.tabs(["WordPress", "Seesaa", "FC2", "Blogger", "Livedoor"])
with _tabs[0]: tab_wordpress()
with _tabs[1]: tab_seesaa()
with _tabs[2]: tab_fc2()
with _tabs[3]: tab_blogger()
with _tabs[4]: tab_livedoor()

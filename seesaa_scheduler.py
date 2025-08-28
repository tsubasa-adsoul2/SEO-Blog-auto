#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Seesaa 予約公開バッチ（無料のGitHub Actionsから定期実行）
- 下書きのタイトル先頭に [YYYY-MM-DD HH:MM]（JST） を付けておく
- その時刻を過ぎたら metaWeblog.editPost(..., publish=True) で公開に切替
- 複数アカウント対応（環境変数 JSON で渡す）
"""

import os
import sys
import json
import re
from datetime import datetime, timedelta, timezone
import xmlrpc.client

JST = timezone(timedelta(hours=9))
SCHEDULE_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\]\s*")

def _now_jst() -> datetime:
    return datetime.now(JST).replace(second=0, microsecond=0)

def _parse_scheduled(title: str):
    """タイトル先頭の [YYYY-MM-DD HH:MM] を抜き出す。"""
    if not title:
        return None
    m = SCHEDULE_RE.match(title.strip())
    if not m:
        return None
    date_str, time_str = m.group(1), m.group(2)
    try:
        y, mo, d = map(int, date_str.split("-"))
        hh, mm = map(int, time_str.split(":"))
        return datetime(y, mo, d, hh, mm, tzinfo=JST)
    except Exception:
        return None

def process_account(name: str, cfg: dict):
    """
    cfg 例：
    {
      "endpoint": "http://blog.seesaa.jp/rpc",
      "blog_id": "kinketsuguide",
      "username": "xxx",
      "password": "xxx",
      "recent_count": 100
    }
    """
    endpoint = cfg["endpoint"]
    blog_id = cfg["blog_id"]
    user = cfg["username"]
    pw = cfg["password"]
    recent = int(cfg.get("recent_count", 100))

    server = xmlrpc.client.ServerProxy(endpoint)

    # 下書きを含む最近の投稿を取得
    posts = server.metaWeblog.getRecentPosts(blog_id, user, pw, recent)

    now = _now_jst()
    changed = 0

    for p in posts:
        # Seesaaは post["postid"], post["title"], post["description"] などが入る
        postid = str(p.get("postid") or p.get("postId") or "")
        title = p.get("title") or ""
        description = p.get("description") or ""
        # 下書き判定（プラットフォームによりキーが異なることがあるので publish=False を条件にする）
        # metaWeblog.getRecentPosts の構造はサービス依存のため、保険としてタイトルの予約タグがないものはスキップ
        sched_at = _parse_scheduled(title)
        if not sched_at:
            continue
        if sched_at <= now:
            # 予約時刻を過ぎていたら公開する
            # タイトル先頭の [日時] を取り除いてきれいにする
            cleaned_title = SCHEDULE_RE.sub("", title, count=1).strip()
            new_struct = {
                "title": cleaned_title or title,
                "description": description,
            }
            # publish=True で公開
            server.metaWeblog.editPost(postid, user, pw, new_struct, True)
            changed += 1
            print(f"[{name}] Published post {postid}: '{cleaned_title}'")

    print(f"[{name}] Done. Published {changed} post(s).")
    return changed

def main():
    # 環境変数 SEESAA_ACCOUNTS_JSON に複数アカ情報を JSON で渡す
    """
    例：
    {
      "arigataya": {
        "endpoint": "http://blog.seesaa.jp/rpc",
        "blog_id": "kinketsuguide",
        "username": "kyuuyo.fac@gmail.com",
        "password": "st13131094pao"
      }
    }
    """
    raw = os.environ.get("SEESAA_ACCOUNTS_JSON")
    if not raw:
        print("SEESAA_ACCOUNTS_JSON is empty", file=sys.stderr)
        sys.exit(1)
    accounts = json.loads(raw)

    total = 0
    for name, cfg in accounts.items():
        try:
            total += process_account(name, cfg)
        except Exception as e:
            print(f"[{name}] ERROR: {e}", file=sys.stderr)

    print(f"Finished. Total published: {total}")

if __name__ == "__main__":
    main()

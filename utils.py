"""ユーティリティ（スラグ生成・日付処理・HTML整形など）"""
import re
import unicodedata
from datetime import datetime, timezone
from typing import Optional




def to_slug(text: str, max_len: int = 80) -> str:
"""簡易スラグ（半角英数とハイフンに規格化）"""
text = unicodedata.normalize("NFKC", text)
text = text.lower()
text = re.sub(r"[^a-z0-9\s-]", "", text)
text = re.sub(r"[\s-]+", "-", text).strip("-")
return text[:max_len] or "post"




def parse_schedule(date_str: str, time_str: str) -> Optional[datetime]:
"""UIの日時入力からUTCへ変換する前の naive datetime を返す。None=予約なし。"""
if not date_str:
return None
try:
hh, mm = (time_str or "00:00").split(":")
local_dt = datetime.strptime(f"{date_str} {hh}:{mm}", "%Y-%m-%d %H:%M")
return local_dt
except Exception:
return None




def ensure_html_blocks(html: str) -> str:
"""最低限の包囲。pタグで囲まれていなければラップ。"""
s = html.strip()
if not s:
return ""
if not ("<p>" in s or "<h" in s or "<ul" in s or "<ol" in s):
s = "\n".join(f"<p>{line}</p>" for line in s.splitlines() if line.strip())
return s

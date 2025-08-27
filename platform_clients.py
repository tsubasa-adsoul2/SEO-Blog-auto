"""
try:
resp = requests.request(method, url, auth=self._auth, timeout=30, **kwargs)
if 200 <= resp.status_code < 300:
return resp
# 403/401等はフォールバック継続
last_exc = Exception(f"{resp.status_code}: {resp.text[:300]}")
except requests.RequestException as e:
last_exc = e
raise last_exc or Exception("WordPress request failed")


# --- Media upload (featured image) ---
def upload_media(self, image: Image.Image, filename: str = "eyecatch.jpg") -> int:
buf = io.BytesIO()
image.save(buf, format="JPEG", quality=85, optimize=True, progressive=True)
buf.seek(0)
headers = {
"Content-Disposition": f"attachment; filename={filename}",
"Content-Type": "image/jpeg",
}
r = self._request_first_ok("POST", "/media", headers=headers, data=buf.getvalue())
data = r.json()
return int(data.get("id"))


# --- Create / Update Post ---
def create_post(
self,
title: str,
content_html: str,
status: str = "draft",
categories: Optional[List[int]] = None,
featured_media: Optional[int] = None,
slug: Optional[str] = None,
date_gmt: Optional[datetime] = None,
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
if date_gmt:
payload["date_gmt"] = date_gmt.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
payload["status"] = "future" # WP予約投稿
r = self._request_first_ok("POST", "/posts", json=payload)
return r.json()




# ---- Placeholders for other platforms (semi-auto / export centric) ----
class SeesaaClient:
def __init__(self, **kwargs):
pass


class FC2Client:
def __init__(self, **kwargs):
pass


class BloggerClient:
def __init__(self, **kwargs):
pass


class LivedoorClient:
def __init__(self, **kwargs):
pass

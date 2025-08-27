res = client.create_post(
    title=data["title"],
    content_html=content_html,
    status="draft" if not dt_local else "future",
    categories=cats,
    featured_media=media_id,
    slug=slug_final,
    date_gmt=date_gmt
)


# --------------------
# タブ: Seesaa / FC2 / Blogger / Livedoor（半自動）
# --------------------


def export_box(platform_name: str, key_prefix: str):
    st.caption(f"{platform_name}: 下記の入力を各プラットフォーム画面にコピペしてください。")
    data = article_form(key_prefix)
    st.divider()
    st.markdown("#### 出力プレビュー（HTML）")
    st.code(ensure_html_blocks(data["body"]) or "", language="html")
    st.download_button(
        label="HTMLとして保存",
        data=ensure_html_blocks(data["body"]) or "",
        file_name=f"{to_slug(data['title'] or 'post')}.html",
        mime="text/html",
        use_container_width=True,
    )





def tab_seesaa():
st.subheader("Seesaa（半自動）")
export_box("Seesaa", "seesaa")




def tab_fc2():
st.subheader("FC2（半自動）")
export_box("FC2", "fc2")




def tab_blogger():
st.subheader("Blogger（半自動）")
export_box("Blogger", "blogger")




def tab_livedoor():
st.subheader("Livedoor（半自動）")
export_box("Livedoor", "livedoor")




# --------------------
# レイアウト
# --------------------
st.title("📤 投稿マシン(v1)")


_tabs = st.tabs(["WordPress", "Seesaa", "FC2", "Blogger", "Livedoor"])
with _tabs[0]:
tab_wordpress()
with _tabs[1]:
tab_seesaa()
with _tabs[2]:
tab_fc2()
with _tabs[3]:
tab_blogger()
with _tabs[4]:
tab_livedoor()

# -*- coding: utf-8 -*-
"""
既存のFC2記事タイトルから日付トークン(240614 等の6〜8桁数字)を除去する一回限りのクリーンアップ。
GitHub Actions(workflow_dispatch)で実行する。直近N件を走査し、該当タイトルのみ editPost で更新。
"""
import os
import re
import sys
import xmlrpc.client

sys.stdout.reconfigure(encoding="utf-8")

FC2_BLOG_ID = os.environ.get("FC2_BLOG_ID", "")
FC2_USERNAME = os.environ.get("FC2_USERNAME", "")
FC2_PASSWORD = os.environ.get("FC2_PASSWORD", "")
FC2_XMLRPC_ENDPOINT = "https://blog.fc2.com/xmlrpc.php"

DATE_RE = re.compile(r"\d{6,8}")
EXT_RE = re.compile(r"\.(?:jpg|jpeg|png|webp|gif)\b", re.IGNORECASE)
NUM_POSTS = int(os.environ.get("CLEANUP_NUM_POSTS", "30"))


def clean_title(title):
    """タイトル中の日付数字を 'Muscle Art' に置換し、漏れた画像拡張子や余分な空白を整える。"""
    new = DATE_RE.sub("Muscle Art", title)
    new = EXT_RE.sub("", new)  # タイトルに混入した .jpg/.png 等を除去
    new = re.sub(r"\s{2,}", " ", new).strip()
    return new


def main():
    if not all([FC2_BLOG_ID, FC2_USERNAME, FC2_PASSWORD]):
        print("Error: FC2 credentials not set")
        return 1
    client = xmlrpc.client.ServerProxy(FC2_XMLRPC_ENDPOINT)
    posts = client.metaWeblog.getRecentPosts(
        FC2_BLOG_ID, FC2_USERNAME, FC2_PASSWORD, NUM_POSTS
    )
    print(f"Fetched {len(posts)} recent posts")
    fixed = 0
    for p in posts:
        title = p.get("title", "")
        post_id = p.get("postid", "")
        if not DATE_RE.search(title):
            continue
        new_title = clean_title(title)
        if new_title == title:
            continue
        struct = {
            "title": new_title,
            "description": p.get("description", ""),
            "categories": p.get("categories", []),
            "mt_keywords": p.get("mt_keywords", ""),
        }
        print(f"Fixing post {post_id}:")
        print(f"  before: {title}")
        print(f"  after : {new_title}")
        ok = client.metaWeblog.editPost(
            str(post_id), FC2_USERNAME, FC2_PASSWORD, struct, True
        )
        print(f"  editPost -> {ok}")
        fixed += 1
    print(f"Done. Fixed {fixed} post(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""
FC2記事の修復ワンショット（GitHub Actions / workflow_dispatch）。

背景: getRecentPosts は本文を +1段エスケープして返す。過去に editPost で
その文字列をそのまま書き戻したため、保存内容が多重エスケープになり本文が
生テキスト表示で壊れた投稿がある。本スクリプトは:
  1) 本文を完全アンエスケープして生HTMLへ復元（破損修復）
  2) タイトルと本文テキストから日付(240614等)・混入拡張子を除去
     （本文は src/href のURLを保護してから置換）
対象は「破損 or タイトルに日付/拡張子」を含む投稿のみ。正常投稿はスキップ。

CLEANUP_MODE=dump で本文の先頭だけ出力する診断モード。
"""
import html
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
ENTITY_RE = re.compile(r"&(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);")
URL_ATTR_RE = re.compile(r'(?:src|href)="[^"]*"')
NUM_POSTS = int(os.environ.get("CLEANUP_NUM_POSTS", "30"))


def fully_unescape(s):
    """エンティティが無くなるまで html.unescape を繰り返し、生HTMLへ戻す。"""
    cur = s
    for _ in range(6):
        if not ENTITY_RE.search(cur):
            break
        cur = html.unescape(cur)
    return cur


def is_corrupted(rep):
    """getRecentPostsの+1段を1回だけ戻した状態にまだエンティティが残る=破損。"""
    return bool(ENTITY_RE.search(html.unescape(rep)))


def clean_title(title):
    new = DATE_RE.sub("Muscle Art", title)
    new = EXT_RE.sub("", new)
    new = re.sub(r"\s{2,}", " ", new).strip()
    return new


def clean_body(body):
    """src/href のURLを保護したうえで、本文テキスト中の日付を 'Muscle Art' に置換。"""
    stash = []

    def _stash(m):
        stash.append(m.group(0))
        return f"\x00{len(stash) - 1}\x00"

    tmp = URL_ATTR_RE.sub(_stash, body)
    tmp = DATE_RE.sub("Muscle Art", tmp)
    for i, v in enumerate(stash):
        tmp = tmp.replace(f"\x00{i}\x00", v)
    return tmp


def main():
    if not all([FC2_BLOG_ID, FC2_USERNAME, FC2_PASSWORD]):
        print("Error: FC2 credentials not set")
        return 1
    client = xmlrpc.client.ServerProxy(FC2_XMLRPC_ENDPOINT)
    posts = client.metaWeblog.getRecentPosts(
        FC2_BLOG_ID, FC2_USERNAME, FC2_PASSWORD, NUM_POSTS
    )
    print(f"Fetched {len(posts)} recent posts")

    if os.environ.get("CLEANUP_MODE") == "dump":
        for p in posts[:8]:
            desc = p.get("description", "")
            print(f"--- post {p.get('postid')} title={p.get('title')!r}")
            print(f"    corrupted={is_corrupted(desc)}  head={desc[:120]!r}")
        return 0

    fixed = 0
    for p in posts:
        title = p.get("title", "")
        post_id = p.get("postid", "")
        rep = p.get("description", "")
        corrupted = is_corrupted(rep)
        new_title = clean_title(title)
        title_changed = new_title != title
        if not (corrupted or title_changed):
            continue
        # 本文を生HTMLへ復元し、日付を除去（URLは保護）
        raw_body = fully_unescape(rep)
        new_body = clean_body(raw_body)
        struct = {
            "title": new_title,
            "description": new_body,
            "categories": p.get("categories", []),
            "mt_keywords": p.get("mt_keywords", ""),
        }
        print(f"Fixing post {post_id}: corrupted={corrupted} title_changed={title_changed}")
        print(f"  title: {title!r} -> {new_title!r}")
        print(f"  body head: {new_body[:90]!r}")
        ok = client.metaWeblog.editPost(
            str(post_id), FC2_USERNAME, FC2_PASSWORD, struct, True
        )
        print(f"  editPost -> {ok}")
        fixed += 1
    print(f"Done. Fixed {fixed} post(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

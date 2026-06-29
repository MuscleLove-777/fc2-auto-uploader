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
# 日付(全数字)やファイル名ハッシュ(英数字)などの「ゴミID」トークン
JUNK_RE = re.compile(r"[0-9a-fA-F]{6,8}")
EXT_RE = re.compile(r"\.(?:jpg|jpeg|png|webp|gif)\b", re.IGNORECASE)


def _junk_sub(m):
    tok = m.group(0)
    digits = sum(c.isdigit() for c in tok)
    # 全数字(=日付/連番) か、全hex文字かつ数字2個以上(=ハッシュ片)のみ置換
    if tok.isdigit() or digits >= 2:
        return "Muscle Art"
    return tok
ENTITY_RE = re.compile(r"&(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);")
# 本文置換時に保護する全HTML属性値(style内の#色コードやsrc/hrefのURL等を守る)
ATTR_RE = re.compile(r'[\w-]+="[^"]*"')
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
    new = JUNK_RE.sub(_junk_sub, title)
    new = EXT_RE.sub("", new)
    new = re.sub(r"\s{2,}", " ", new).strip()
    return new


def clean_body(body):
    """全HTML属性値(style内の色コードやURL)を保護し、本文テキスト中のゴミIDのみ置換。"""
    stash = []

    def _stash(m):
        stash.append(m.group(0))
        return f"\x00{len(stash) - 1}\x00"

    tmp = ATTR_RE.sub(_stash, body)
    tmp = JUNK_RE.sub(_junk_sub, tmp)
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

    if os.environ.get("CLEANUP_MODE") == "meta":
        for p in posts:
            meta = {k: v for k, v in p.items() if k != "description"}
            print(f"post {p.get('postid')}: {meta}")
        return 0

    if os.environ.get("CLEANUP_MODE") == "delete":
        target = os.environ.get("REPUBLISH_ID", "")
        exists = any(str(p.get("postid")) == str(target) for p in posts)
        if not exists:
            print(f"post {target} not found (already deleted?)")
            return 0
        print(f"Deleting post {target}")
        ok = client.blogger.deletePost(
            "", str(target), FC2_USERNAME, FC2_PASSWORD, True
        )
        print(f"  deletePost -> {ok}")
        return 0

    if os.environ.get("CLEANUP_MODE") == "rebuild_fanza":
        target = os.environ.get("REPUBLISH_ID", "")
        import importlib.util
        spec = importlib.util.spec_from_file_location("upload", "upload.py")
        up = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(up)
        for p in posts:
            if str(p.get("postid")) != str(target):
                continue
            raw = fully_unescape(p.get("description", ""))
            m_img = re.search(r'<img[^>]+src="([^"]+)"', raw)
            image_url = os.environ.get("REPUBLISH_IMAGE", "") or (m_img.group(1) if m_img else "")
            title = p.get("title", "") or "🔞 筋肉女子の腹筋がエグい作品まとめ｜FANZA厳選"
            _, body, _ = up.build_fanza_article(image_url, title=title)
            struct = {
                "title": title,
                "description": body,
                "categories": ["筋肉女子"],
                "mt_keywords": p.get("mt_keywords", ""),
            }
            print(f"Rebuilding FANZA post {target} (image={image_url[:60]!r})")
            ok = client.metaWeblog.editPost(
                str(target), FC2_USERNAME, FC2_PASSWORD, struct, True
            )
            print(f"  editPost -> {ok}")
            return 0
        print(f"post {target} not found")
        return 1

    if os.environ.get("CLEANUP_MODE") == "republish":
        target = os.environ.get("REPUBLISH_ID", "")
        new_cat = os.environ.get("REPUBLISH_CATEGORY", "筋肉女子")
        for p in posts:
            if str(p.get("postid")) != str(target):
                continue
            raw_body = fully_unescape(p.get("description", ""))
            body_out = clean_body(raw_body)
            if os.environ.get("REPUBLISH_STRIP_FANZA") == "1":
                # al.dmm.co.jp を含む div ブロックを丸ごと除去（FC2非公開化の原因切り分け）
                body_out = re.sub(
                    r"<div[^>]*>(?:(?!</div>).)*al\.dmm\.co\.jp(?:(?!</div>).)*</div>",
                    "", body_out, flags=re.DOTALL,
                )
            struct = {
                "title": clean_title(p.get("title", "")),
                "description": body_out,
                "categories": [new_cat] if new_cat else [],
                "mt_keywords": p.get("mt_keywords", ""),
            }
            print(f"Republishing post {target} with category={new_cat!r}")
            ok = client.metaWeblog.editPost(
                str(target), FC2_USERNAME, FC2_PASSWORD, struct, True
            )
            print(f"  editPost -> {ok}")
            return 0
        print(f"post {target} not found")
        return 1

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

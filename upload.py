# -*- coding: utf-8 -*-
"""
FC2 Blog 画像自動アップロード（GitHub Actions用）
Google Driveから画像取得 → FC2 BlogにXML-RPC (MetaWeblog API) で投稿
"""
import sys
import json
import os
import random
import time
import xmlrpc.client
from datetime import datetime, timezone, timedelta

import gdown

JST = timezone(timedelta(hours=9))

# --- 環境変数 ---
FC2_BLOG_ID = os.environ.get("FC2_BLOG_ID", "")
FC2_USERNAME = os.environ.get("FC2_USERNAME", "")
FC2_PASSWORD = os.environ.get("FC2_PASSWORD", "")
GDRIVE_FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID_FC2", "")

FC2_XMLRPC_ENDPOINT = "https://blog.fc2.com/xmlrpc.php"
PATREON_LINK = "https://www.patreon.com/cw/MuscleLove"
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
UPLOADED_LOG = "uploaded_fc2.json"

# --- タグマッピング ---
CONTENT_TAG_MAP = {
    'training': ['筋トレ', 'ワークアウト', 'トレーニング', 'ジム', 'フィットネス'],
    'workout': ['筋トレ', 'ワークアウト', 'トレーニング', 'ジム', 'フィットネス'],
    'pullups': ['懸垂', 'プルアップ', '背中トレ', '自重トレーニング'],
    'posing': ['ポージング', 'ボディビル', 'フィジーク'],
    'flex': ['フレックス', '筋肉', 'ボディビル'],
    'muscle': ['筋肉', 'マッスル', 'フィットネス'],
    'bicep': ['上腕二頭筋', '腕トレ', 'バイセップス'],
    'abs': ['腹筋', 'シックスパック', '体幹'],
    'leg': ['脚トレ', 'レッグデイ', 'スクワット'],
    'back': ['背中', '広背筋', '背中トレ'],
    'squat': ['スクワット', '脚トレ', 'レッグデイ'],
    'deadlift': ['デッドリフト', 'パワーリフティング'],
    'bench': ['ベンチプレス', '胸トレ'],
    'bikini': ['ビキニ', 'ビキニフィットネス', 'フィギュア'],
    'competition': ['大会', 'コンテスト', 'ボディビル'],
}

BASE_TAGS = [
    '筋肉女子', '筋トレ女子', 'フィットネス', 'マッスルガール',
    'ボディビル', 'ジム', 'ワークアウト', 'MuscleLove',
]

# --- タイトルテンプレート ---
TITLE_TEMPLATES = [
    "💪 {category} | MuscleLove",
    "🔥 {category} ～筋肉美の世界～",
    "✨ {category} | マッスルラブ",
    "💪 {category} ～美しき筋肉～",
    "🔥 MuscleLove | {category}",
    "{category} ～フィットネスアート～ ✨",
    "💪 {category} ～強く美しく～",
    "🔥 {category} | 筋肉女子の魅力",
]

# --- 本文HTMLテンプレート ---
BODY_TEMPLATES = [
    """<div style="text-align:center;">
<p><img src="{image_url}" alt="{title}" style="max-width:100%;" /></p>
<p style="font-size:1.1em;"><strong>{title}</strong></p>
<p>{description}</p>
<p style="margin-top:20px;">{hashtags}</p>
<hr />
<p style="font-size:1.2em;">🔥 <a href="{patreon_link}" target="_blank"><strong>もっと見たい方はPatreonへ → MuscleLove</strong></a> 🔥</p>
</div>""",
    """<div style="text-align:center;">
<p><img src="{image_url}" alt="{title}" style="max-width:100%;" /></p>
<p style="font-size:1.1em;"><strong>✨ {title} ✨</strong></p>
<p>{description}</p>
<p style="margin-top:20px;">{hashtags}</p>
<hr />
<p style="font-size:1.2em;">💪 <a href="{patreon_link}" target="_blank"><strong>限定コンテンツはPatreonで公開中！</strong></a> 💪</p>
</div>""",
    """<div style="text-align:center;">
<p><img src="{image_url}" alt="{title}" style="max-width:100%;" /></p>
<p style="font-size:1.1em;"><strong>{title}</strong></p>
<p>{description}</p>
<p style="margin-top:20px;">{hashtags}</p>
<hr />
<p style="font-size:1.2em;">🔥 <a href="{patreon_link}" target="_blank"><strong>Patreonで限定写真・動画を配信中！</strong></a></p>
<p>👉 <a href="{patreon_link}" target="_blank">{patreon_link}</a></p>
</div>""",
]

# --- 説明文テンプレート ---
DESCRIPTION_TEMPLATES = [
    "筋肉美の極み。鍛え上げられた肉体の美しさをご覧ください。",
    "強さと美しさを兼ね備えた筋肉女子の魅力をお届けします。",
    "MuscleLoveが厳選した筋肉美の世界。フィットネスの素晴らしさを感じてください。",
    "鍛え上げた身体は芸術。筋肉女子たちの美しいボディをお楽しみください。",
    "フィットネスは人生を変える。美しく鍛え上げられた身体の魅力。",
    "筋トレ女子の美しさに心奪われる。MuscleLoveのフィットネスアート。",
]


# ===== Google Drive =====

def download_images():
    """Google Driveからgdownで画像をダウンロード"""
    dl_dir = "images"
    os.makedirs(dl_dir, exist_ok=True)
    url = f"https://drive.google.com/drive/folders/{GDRIVE_FOLDER_ID}"
    print(f"Downloading from Google Drive: {url}")
    try:
        gdown.download_folder(url, output=dl_dir, quiet=False, remaining_ok=True)
    except Exception as e:
        print(f"Download error: {e}")
        return []

    images = []
    for root, dirs, filenames in os.walk(dl_dir):
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext in IMAGE_EXTENSIONS:
                fpath = os.path.join(root, fname)
                images.append({
                    "name": fname,
                    "local_path": fpath,
                })
    return images


# ===== タグ・タイトル・本文生成 =====

def generate_tags(image_name):
    """ファイル名からタグを生成"""
    tags = list(BASE_TAGS)
    name_lower = image_name.lower().replace('-', ' ').replace('_', ' ')
    matched = set()
    for keyword, keyword_tags in CONTENT_TAG_MAP.items():
        if keyword in name_lower:
            for t in keyword_tags:
                if t not in matched:
                    tags.append(t)
                    matched.add(t)
    seen = set()
    unique_tags = []
    for t in tags:
        if t.lower() not in seen:
            seen.add(t.lower())
            unique_tags.append(t)
    return unique_tags


def extract_category(image_name):
    """ファイル名からカテゴリを推定"""
    parts = image_name.replace('-', ' ').replace('_', ' ').split()
    skip = {'jpg', 'jpeg', 'png', 'webp', 'gif'}
    for p in parts:
        if p.lower() not in skip and len(p) > 2:
            return p.capitalize()
    return "Muscle Art"


def build_title(image_name):
    """記事タイトルを生成"""
    category = extract_category(image_name)
    template = random.choice(TITLE_TEMPLATES)
    return template.format(category=category)


def build_body(image_url, title, tags):
    """記事本文HTMLを生成"""
    description = random.choice(DESCRIPTION_TEMPLATES)
    hashtags = ' '.join([f'#{t}' for t in tags[:15]])
    template = random.choice(BODY_TEMPLATES)
    return template.format(
        image_url=image_url,
        title=title,
        description=description,
        hashtags=hashtags,
        patreon_link=PATREON_LINK,
    )


# ===== FC2 Blog XML-RPC =====

XMLRPC_TIMEOUT = 120  # seconds
XMLRPC_MAX_RETRIES = 5
XMLRPC_RETRY_DELAYS = [10, 30, 60, 90, 120]  # seconds between retries


class TimeoutTransport(xmlrpc.client.Transport):
    """XML-RPC Transport with configurable timeout"""
    def __init__(self, timeout=XMLRPC_TIMEOUT, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self.timeout
        return conn


class TimeoutSafeTransport(xmlrpc.client.SafeTransport):
    """XML-RPC SafeTransport (HTTPS) with configurable timeout"""
    def __init__(self, timeout=XMLRPC_TIMEOUT, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self.timeout
        return conn


def get_fc2_client():
    """FC2 Blog XML-RPCクライアントを作成（タイムアウト付き）"""
    transport = TimeoutSafeTransport(timeout=XMLRPC_TIMEOUT)
    return xmlrpc.client.ServerProxy(FC2_XMLRPC_ENDPOINT, transport=transport)


def xmlrpc_call_with_retry(func, *args, max_retries=XMLRPC_MAX_RETRIES, delays=None):
    """XML-RPC呼び出しをリトライ付きで実行"""
    if delays is None:
        delays = XMLRPC_RETRY_DELAYS
    last_error = None
    for attempt in range(max_retries):
        try:
            return func(*args)
        except xmlrpc.client.Fault:
            raise  # API-level errors should not be retried
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait = delays[min(attempt, len(delays) - 1)]
                print(f"  Connection error (attempt {attempt + 1}/{max_retries}): {e}")
                print(f"  Retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"  All {max_retries} attempts failed: {e}")
    raise last_error


def verify_credentials(client):
    """認証情報を確認（リトライ付き）"""
    try:
        blogs = xmlrpc_call_with_retry(
            client.blogger.getUsersBlogs, "fc2", FC2_USERNAME, FC2_PASSWORD
        )
        if blogs:
            print(f"Auth OK: Blog ID = {blogs[0].get('blogid', 'unknown')}")
            print(f"Blog name: {blogs[0].get('blogName', 'unknown')}")
            return True
        else:
            print("Auth failed: No blogs found")
            return False
    except xmlrpc.client.Fault as e:
        print(f"Auth error: {e.faultString}")
        return False
    except Exception as e:
        print(f"Connection error: {e}")
        return False


def upload_image_to_fc2(client, image_path):
    """画像をFC2 Blogにアップロード → URLを返す"""
    fname = os.path.basename(image_path)
    ext = os.path.splitext(fname)[1].lower()

    mime_map = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
    }
    mime_type = mime_map.get(ext, 'image/jpeg')

    with open(image_path, 'rb') as f:
        image_data = f.read()

    media_struct = {
        'name': fname,
        'type': mime_type,
        'bits': xmlrpc.client.Binary(image_data),
    }

    print(f"Uploading image: {fname} ({mime_type}, {len(image_data)} bytes)")
    result = xmlrpc_call_with_retry(
        client.metaWeblog.newMediaObject,
        FC2_BLOG_ID, FC2_USERNAME, FC2_PASSWORD, media_struct
    )
    image_url = result.get('url', '')
    print(f"Image uploaded: {image_url}")
    return image_url


def create_blog_post(client, title, body, tags, publish=True):
    """FC2 Blogに記事を投稿"""
    post_struct = {
        'title': title,
        'description': body,
        'categories': ['筋肉女子'],
        'mt_keywords': ','.join(tags[:20]),
    }

    print(f"Creating post: {title}")
    post_id = xmlrpc_call_with_retry(
        client.metaWeblog.newPost,
        FC2_BLOG_ID, FC2_USERNAME, FC2_PASSWORD, post_struct, publish
    )
    print(f"Post created! ID: {post_id}")
    return post_id


# ===== アップロードログ =====

def load_uploaded_log():
    if os.path.exists(UPLOADED_LOG):
        with open(UPLOADED_LOG, 'r') as f:
            return json.load(f)
    return []


def save_uploaded_log(log):
    with open(UPLOADED_LOG, 'w') as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


# ===== メイン =====

def main():
    # 認証チェック
    if not FC2_BLOG_ID:
        print("Error: FC2_BLOG_ID not set")
        return 1
    if not FC2_USERNAME:
        print("Error: FC2_USERNAME not set")
        return 1
    if not FC2_PASSWORD:
        print("Error: FC2_PASSWORD not set")
        return 1
    if not GDRIVE_FOLDER_ID:
        print("Error: GDRIVE_FOLDER_ID_FC2 not set")
        return 1

    print("FC2 Blog Auto Uploader (XML-RPC)")
    print(f"Time: {datetime.now(JST).strftime('%Y-%m-%d %H:%M JST')}")
    print()

    # FC2 Blog接続
    client = get_fc2_client()
    if not verify_credentials(client):
        return 1

    # Google Driveから画像ダウンロード
    images = download_images()
    if not images:
        print("No images found!")
        return 0

    # 未アップロード画像をフィルタ
    uploaded_log = load_uploaded_log()
    uploaded_names = set(uploaded_log)
    available = [img for img in images if img["name"] not in uploaded_names]
    if not available:
        print("All images already uploaded!")
        return 0

    print(f"Available: {len(available)} / Total: {len(images)}")

    # ランダムに1枚選択
    image = random.choice(available)
    print(f"Selected: {image['name']}")

    # タグ生成
    tags = generate_tags(image["name"])

    # トレンドタグ追加
    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl='ja-JP', tz=540)
        trending = pytrends.trending_searches(pn='japan')
        if trending is not None and not trending.empty:
            trend_list = trending[0].tolist()[:5]
            seen = {t.lower() for t in tags}
            for t in trend_list:
                if t.lower() not in seen:
                    tags.append(str(t))
                    seen.add(t.lower())
            print(f"Trend tags added: {trend_list}")
    except Exception as e:
        print(f"Trend tags skipped: {e}")

    print(f"Tags: {', '.join(tags[:10])}...")

    try:
        # 1. 画像をFC2にアップロード
        image_url = upload_image_to_fc2(client, image["local_path"])
        if not image_url:
            print("Error: Failed to get image URL")
            return 1

        # 2. タイトル・本文生成
        title = build_title(image["name"])
        body = build_body(image_url, title, tags)
        print(f"Title: {title}")

        # 3. ブログ記事を投稿
        post_id = create_blog_post(client, title, body, tags, publish=True)

        # 成功 → ログ保存
        uploaded_log.append(image["name"])
        save_uploaded_log(uploaded_log)
        print(f"\nSuccess! Post ID: {post_id}")
        print(f"Remaining: {len(available) - 1}")
        return 0

    except xmlrpc.client.Fault as e:
        print(f"XML-RPC Error: {e.faultCode} - {e.faultString}")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())

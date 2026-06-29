# -*- coding: utf-8 -*-
"""
FC2 Blog 画像自動アップロード（GitHub Actions用）
Google Driveから画像取得 → FC2 BlogにXML-RPC (MetaWeblog API) で投稿
"""
import argparse
import html
import sys
import json
import os
import random
import re
import time
import xmlrpc.client
from datetime import datetime, timezone, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# Windowsローカル(cp932)でも絵文字ログでクラッシュしないようUTF-8出力に統一
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    import gdown
except ImportError:
    gdown = None
try:
    from pool_loader import as_insights
except Exception:
    as_insights = None

JST = timezone(timedelta(hours=9))

# --- 環境変数 ---
FC2_BLOG_ID = os.environ.get("FC2_BLOG_ID", "")
FC2_USERNAME = os.environ.get("FC2_USERNAME", "")
FC2_PASSWORD = os.environ.get("FC2_PASSWORD", "")
# 画像取得元: DeviantArtと同じDriveフォルダを使う（GDRIVE_FOLDER_ID）。
# 旧 GDRIVE_FOLDER_ID_FC2 が設定済みの環境向けに後方互換でフォールバック。
GDRIVE_FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID", "") or os.environ.get("GDRIVE_FOLDER_ID_FC2", "")

FC2_XMLRPC_ENDPOINT = "https://blog.fc2.com/xmlrpc.php"
PATREON_LINK = "https://www.patreon.com/c/MuscleLove?utm_source=fc2"
X_LINK = "https://x.com/MuscleGirlLove7"

# --- FANZA(DMM)アフィリエイト ---
# 重要: FC2は本文に al.dmm.co.jp(FANZAアフィリ直リンク)を含む記事を自動で非公開化(404)する。
# そのため記事面では自サイトハブ(musclelove-777.github.io)へ誘導し、FANZAアフィリ計測は
# ハブ側で行う(コンプライアンス安全・FC2で表示可能)。af_id/直リンクは参照用に保持。
FANZA_AF_ID = "pinky2400-003"
FANZA_LINK = (
    "https://al.dmm.co.jp/?lurl=https%3A%2F%2Fvideo.dmm.co.jp%2Fav%2Flist%2F%3Fkeyword%3D%E8%85%B9%E7%AD%8B"
    f"&af_id={FANZA_AF_ID}&ch=link_tool&ch_id=text"
)
# 記事面の誘導先 = 自サイトのFANZA作品ガイドハブ（adult_fanzaレーンのpriority_url）
FANZA_FUNNEL_URL = "https://musclelove-777.github.io/?utm_source=fc2&utm_medium=fanza"
# 記事下部に差し込むFANZA誘導カード（PR表記=ステマ規制対応 / 18禁注記付き）
FANZA_BLOCK_HTML = (
    '<div style="text-align:center; background:#2a0a12; padding:20px; border-radius:10px; margin:20px 0;">'
    '<p style="font-size:1.25em; color:#ff4d6d;">🔞 筋肉×腹筋が際立つFANZA作品をもっと見たい人へ</p>'
    f'<p style="font-size:1.1em;"><a href="{FANZA_FUNNEL_URL}" target="_blank" rel="noopener" '
    'style="color:#ff8fa3; text-decoration:underline;">👉 FANZA作品ガイド・ランキングはこちら 👈</a></p>'
    '<p style="font-size:0.8em; color:#999;">※18歳未満は閲覧不可 ／ PR</p>'
    '</div>'
)
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
UPLOADED_LOG = "uploaded_fc2.json"
DRY_RUN_OUTPUT = os.environ.get("DRY_RUN_OUTPUT", "dry_run_fc2_article.html")
LOCAL_IMAGE_FILES = ["og.png"]
LOCAL_IMAGE_DIRS = ["images"]
URL_RE = re.compile(r"https?://[^\s<]+")
_POOL_INSIGHTS = None

# --- MuscleLove バックリンクプール（FC2はadult OKだがフィットネス系で安全運転） ---
ML_BACKLINK_POOL_FITNESS = [
    ("https://musclelove-777.github.io/muscle-meal-girls/", "筋肉女子のマッスルメシ"),
    ("https://musclelove-777.github.io/runners-lab/", "ランナーラボ"),
    ("https://musclelove-777.github.io/armwrestling-girls-navi/", "腕相撲女子ナビ"),
    ("https://musclelove-777.github.io/physique-girls-navi/", "フィジーク女子ナビ"),
    ("https://musclelove-777.github.io/fighting-girls-navi/", "格闘技女子ナビ"),
    ("https://musclelove-777.github.io/joshi-prowrestling-navi/", "女子プロレスナビ"),
    ("https://musclelove-777.github.io/female-physique-queens/", "Female Physique Queens"),
    ("https://musclelove-777.github.io/network/fitness/", "Fitness Network 15サイト"),
    ("https://musclelove-777.github.io/network/academy/", "MuscleLove Academy 77"),
]


def build_x_block():
    """X(旧Twitter)へのリンクブロック（全記事に付与、冪等マーカー付き）"""
    return (
        "\n<br/>\n"
        "<!-- ML_X_LINK -->\n"
        f'<p style="font-size:1.1em;">🐦 <a href="{X_LINK}" target="_blank" rel="noopener">'
        'X（旧Twitter）でもほぼ毎日更新中！ → @MuscleGirlLove7</a></p>\n'
        "<!-- /ML_X_LINK -->\n"
    )


def build_backlink_block():
    """MuscleLoveバックリンクHTMLブロック（ランダム3件、冪等マーカー付き）"""
    try:
        k = min(3, len(ML_BACKLINK_POOL_FITNESS))
        selected = random.sample(ML_BACKLINK_POOL_FITNESS, k=k)
        items = " | ".join([f'<a href="{u}" target="_blank" rel="noopener">{n}</a>' for u, n in selected])
        return (
            "\n<br/><br/>\n"
            "<!-- ML_BACKLINK -->\n"
            f'<small style="color:#888;">💡 関連サイト：{items}</small>\n'
            "<!-- /ML_BACKLINK -->\n"
        )
    except Exception:
        return ""


def env_truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def load_safe_pool():
    """Read dashboard/autonomy content_pool through the local uploader copy."""
    global _POOL_INSIGHTS
    if _POOL_INSIGHTS is not None:
        return _POOL_INSIGHTS
    if as_insights is None:
        _POOL_INSIGHTS = {}
        return _POOL_INSIGHTS
    try:
        _POOL_INSIGHTS = as_insights("safe_fitness", platform="fc2") or {}
    except Exception as e:
        print(f"content_pool skipped: {e}")
        _POOL_INSIGHTS = {}
    return _POOL_INSIGHTS


def merge_unique(base, extra, deny=None):
    deny = {str(x).strip().lower() for x in (deny or []) if str(x).strip()}
    merged = []
    seen = set()
    for value in list(base or []) + list(extra or []):
        text = str(value).strip()
        key = text.lower()
        if not text or key in seen or key in deny:
            continue
        seen.add(key)
        merged.append(text)
    return merged


def pool_caption(tags):
    pool = load_safe_pool()
    templates = pool.get("recommended_templates") or []
    if not templates:
        return ""
    hashtags = " ".join([f"#{t}" for t in tags[:10]])
    template = random.choice(templates)
    try:
        return template.format(hashtags=hashtags, tags=hashtags)
    except Exception:
        return str(template)


def linkify_text(text):
    escaped = html.escape(str(text))

    def repl(match):
        url = match.group(0)
        safe_url = html.escape(url, quote=True)
        return f'<a href="{safe_url}" target="_blank" rel="noopener">{safe_url}</a>'

    return URL_RE.sub(repl, escaped)


def build_pool_cta_block():
    pool = load_safe_pool()
    ctas = [str(c).strip() for c in pool.get("recommended_ctas", []) if str(c).strip()]
    if not ctas:
        return ""
    cta = random.choice(ctas)
    return (
        "\n<br/>\n"
        "<!-- ML_CONTENT_POOL_CTA -->\n"
        f'<p style="font-size:1.05em;">{linkify_text(cta)}</p>\n'
        "<!-- /ML_CONTENT_POOL_CTA -->\n"
    )

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
    'ワキフェチ', '腕フェチ', '筋肉美', 'AI美女',
    'むちむち', '褐色美女',
]

# --- タイトルテンプレート ---
TITLE_TEMPLATES = [
    # 凛花（ギャル・ドS）「ウチ」褐色テカテカ腹筋バキバキ巨乳
    "💪 はぁ？ウチの{category}見たいわけ？笑 | 凛花",
    "🔥 凛花の{category}、まじバキバキすぎて語彙力ゼロになった",
    "✨ しょーがないなぁ、特別に見せてあげる♡ 凛花の{category}",
    "💪 「硬いよ？覚悟しな♡」凛花の{category}でKOされた人続出",
    # カイ（ボーイッシュ）「ウチ」小麦肌アスリートお尻プリッ
    "🔥 よっ！カイの{category}、まじやばくない？",
    "✨ カイの{category} — 腕立て500回の成果がこれ",
    "💪 「照れるじゃん笑」カイの{category}、ウチ的には限界っしょ",
    "🔥 小麦肌×アスリート×{category}。カイの仕上がりが神すぎる",
    # ましろ（天然）「あたし」色白もちもち汗っかきおっぱい大きめ
    "✨ えへへ〜ましろの{category}見てく？♡",
    "💪 ましろの{category}、もちもちなのにバキバキな件",
    "🔥 「えっまじ！？うれし〜♡ もっと言って！」ましろの{category}を褒めよう",
    "♡ ましろの汗テカテカ{category}、オイル塗ったみたいじゃん笑",
    # 紫苑（お姉さん系）「あたし」長身グラマラス褐色爆乳フェロモン
    "💪 あ〜ら♡ 紫苑の{category}、興味あるんだ？かわい〜",
    "🔥 「触ったら戻れないかもよ？笑」紫苑の{category}が全開",
    "✨ 紫苑の{category}、汗でフェロモンやばすぎる件",
    "♡ 「そんな見つめられたら…ドキドキしちゃうじゃん♡」紫苑の{category}",
    # アヤネ（ツンデレ）「あたし」コンパクトむちむちツインテール色白
    "💪 な、なに見てんの！アヤネの{category}…見ていいけど",
    "🔥 「3秒だけだからね！ちゃんと見なさいよ」アヤネの{category}",
    "✨ ふ〜ん…褒めてくれるなら悪い気しないけどさ。アヤネの{category}",
    "♡ アヤネの{category} — ツンデレが最終的に全部見せてくれる件",
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
    # 凛花（ギャル・ドS）
    "💪 「はぁ？ウチの身体そんな見たいわけ？笑　しょーがないなぁ、特別ね♡」— 今日の凛花の腹筋、ガチでバキバキすぎる",
    "🔥 凛花の褐色テカテカボディ。腹筋バキバキなのにむちむちっていう矛盾が最高すぎる♡",
    "✨ 「いーけど、硬いよ？覚悟しな♡」← 凛花のこのセリフで毎回KOされる件",
    "💪 「めっちゃ汗かいたわ〜ワキとかやばくない？笑」今日の凛花も破壊力満点",
    # カイ（ボーイッシュ）
    "🔥 「よっ！今日もジム行ってきた〜！てかこの腕見てよまじやばくない？」カイの小麦肌が本日も神",
    "✨ 「ワキ？笑　別にいーけどさぁ〜汗くさくね？あはは！」カラッとしてるカイが最高すぎる",
    "💪 ボーイッシュなのにお尻プリッ、肩幅しっかり。カイのこのバランス、反則じゃない？",
    "🔥 「照れるじゃん笑」って言いながら全然隠さないカイ、最高",
    # ましろ（天然）
    "✨ 「えへへ〜今日もめっちゃトレーニングしたぁ！あたしがんばった〜♡」ましろのもちもち筋肉が今日も最高",
    "💪 「えっまじ！？うれし〜！♡ もっと言って言って〜！」褒めると喜ぶましろを無限に褒めたい",
    "🔥 「なんかさぁ〜めっちゃ身体テカテカしてない？オイル塗ったみたいじゃん笑」ましろの汗テカ現象、神",
    "♡ 色白もちもち＋腹筋うっすら＋おっぱい大きめ。ましろの体型の神バランス",
    # 紫苑（お姉さん系）
    "💪 「あ〜ら♡ あたしの身体に興味あるんだ？かわい〜♡」紫苑の長身グラマラスボディ今日も全開",
    "🔥 「触ったらもう戻れないかもよ？笑」大胸筋×爆乳の紫苑。この組み合わせは反則すぎる",
    "✨ 「全身びっしょりなんだけど♡ えっちくない？笑」紫苑の汗フェロモンでKOされた",
    "♡ 「そんな見つめられたら〜…あたしもドキドキしちゃうじゃん♡」紫苑のこの余裕、惚れる",
    # アヤネ（ツンデレ）
    "💪 「な、なに見てんの！…見るなとは言ってないけど！笑」アヤネのコンパクトむちむち筋肉が本日も破壊",
    "🔥 「3秒だけだからね！…ちゃんと触りなさいよ」← アヤネさん、ちゃんと見ていいって言ってくれてますよ？",
    "✨ 「ふ〜ん…そ、そう？…もっと言いなよ（小声）」赤くなるアヤネのツインテールがかわいすぎる",
    "♡ 「うわ〜やば〜汗めっちゃ…やだ見ないでよぉ…いや別に見ていいけど！」アヤネのノリ最高",
]


# ===== Google Drive =====

def download_images():
    """Google Driveからgdownで画像をダウンロード"""
    if gdown is None:
        print("Download error: gdown is not installed")
        return []
    dl_dir = "images"
    os.makedirs(dl_dir, exist_ok=True)
    url = f"https://drive.google.com/drive/folders/{GDRIVE_FOLDER_ID}"
    print(f"Downloading from Google Drive: {url}")
    try:
        # gdownのバージョン差で remaining_ok が無い場合があるため、TypeErrorで外して再試行
        try:
            gdown.download_folder(url, output=dl_dir, quiet=False, remaining_ok=True)
        except TypeError:
            gdown.download_folder(url, output=dl_dir, quiet=False)
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
    pool = load_safe_pool()
    return merge_unique(unique_tags, pool.get("recommended_tags", []), pool.get("avoid_tags", []))


def extract_category(image_name):
    """ファイル名からカテゴリを推定（日付・連番などの数字トークンは除外）"""
    name = os.path.splitext(image_name)[0]  # 拡張子を除去
    parts = name.replace('-', ' ').replace('_', ' ').split()
    skip = {'jpg', 'jpeg', 'png', 'webp', 'gif'}
    for p in parts:
        if p.lower() in skip or len(p) <= 2:
            continue
        # 240614 のような日付・数字のみのトークンはタイトルに出さない
        if re.fullmatch(r'\d+', p):
            continue
        return p.capitalize()
    return "Muscle Art"


def build_title(image_name):
    """記事タイトルを生成"""
    category = extract_category(image_name)
    template = random.choice(TITLE_TEMPLATES)
    return template.format(category=category)


def build_body(image_url, title, tags):
    """記事本文HTMLを生成"""
    description = pool_caption(tags) or random.choice(DESCRIPTION_TEMPLATES)
    hashtags = ' '.join([f'#{t}' for t in tags[:15]])
    template = random.choice(BODY_TEMPLATES)
    body = template.format(
        image_url=image_url,
        title=title,
        description=description,
        hashtags=hashtags,
        patreon_link=PATREON_LINK,
    )
    return body.rstrip() + build_x_block() + build_backlink_block() + build_pool_cta_block()


# ===== FANZA アフィリエイト記事 =====

FANZA_TITLE_TEMPLATES = [
    "🔞 筋肉女子の腹筋がエグい作品まとめ｜FANZA厳選",
    "🔞 バキバキ腹筋×美女。FANZAで見つけた神作品",
    "🔞 筋肉美女好きが選ぶFANZAおすすめ作品",
    "🔞 腹筋フェチ必見。FANZAの仕上がりエグい作品",
    "🔞 アスリート系美女作品をFANZAでチェック",
]

FANZA_INTRO_TEMPLATES = [
    "MuscleLoveがお届けする筋肉女子の世界。さらに刺激が欲しい大人の方には、FANZAの腹筋エグい作品もおすすめです。",
    "バキバキに鍛えられた腹筋と、しなやかな筋肉美。もっとディープに楽しみたい方はFANZAでどうぞ。",
    "筋肉×美しさの究極系。下のリンクから、FANZAで腹筋が際立つ作品をチェックできます。",
]


def build_fanza_article(image_url, title=None):
    """FANZAアフィリエイト用の独立記事（タイトル・本文・タグ）を生成。

    メイン記事と同じ画像URLを再利用して視覚的に繋げつつ、FANZA CTA・Patreon・Xを付与する。
    """
    fanza_title = title or random.choice(FANZA_TITLE_TEMPLATES)
    intro = random.choice(FANZA_INTRO_TEMPLATES)
    img_html = (
        f'<p><img src="{image_url}" alt="{fanza_title}" style="max-width:100%;" /></p>\n'
        if image_url else ""
    )
    body = (
        '<div style="text-align:center;">\n'
        f'{img_html}'
        f'<p style="font-size:1.1em;"><strong>{fanza_title}</strong></p>\n'
        f'<p>{intro}</p>\n'
        f'{FANZA_BLOCK_HTML}\n'
        '<hr />\n'
        f'<p style="font-size:1.1em;">🔥 <a href="{PATREON_LINK}" target="_blank">'
        '<strong>未公開コンテンツはPatreonへ → MuscleLove</strong></a></p>\n'
        '</div>'
    )
    body = body.rstrip() + build_x_block() + build_backlink_block()
    # FANZA記事のタグ（adult寄り。ベースは筋肉女子テーマ）
    tags = ['筋肉美女', 'マッスル', '腹筋女子', 'FANZA', 'アスリート系', 'AI美女', 'MuscleLove']
    return fanza_title, body, tags


# ===== FC2 Blog XML-RPC =====

XMLRPC_TIMEOUT = 300  # seconds
XMLRPC_MAX_RETRIES = 7
XMLRPC_RETRY_DELAYS = [10, 30, 60, 90, 120, 180, 240]  # seconds between retries


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


def create_blog_post(client, title, body, tags, publish=True, categories=None):
    """FC2 Blogに記事を投稿"""
    post_struct = {
        'title': title,
        'description': body,
        'categories': categories or ['筋肉女子'],
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


def file_url(path):
    return "file:///" + os.path.abspath(path).replace(os.sep, "/")


def scan_local_images():
    images = []
    for fname in LOCAL_IMAGE_FILES:
        if os.path.exists(fname):
            images.append({"name": fname, "local_path": os.path.abspath(fname)})
    for dirname in LOCAL_IMAGE_DIRS:
        if not os.path.isdir(dirname):
            continue
        for root, dirs, filenames in os.walk(dirname):
            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext in IMAGE_EXTENSIONS:
                    path = os.path.join(root, fname)
                    images.append({"name": fname, "local_path": os.path.abspath(path)})
    return images


def write_dry_run_preview(title, body, tags, image):
    tag_line = ", ".join(tags[:20])
    image_path = image.get("local_path", "")
    preview = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)}</title>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  <p><strong>Image:</strong> {html.escape(image_path)}</p>
  <p><strong>Tags:</strong> {html.escape(tag_line)}</p>
  <hr>
{body}
</body>
</html>
"""
    with open(DRY_RUN_OUTPUT, "w", encoding="utf-8") as f:
        f.write(preview)
    print(f"DRY_RUN preview wrote: {DRY_RUN_OUTPUT}")


def run_dry_run():
    print("FC2 Blog Auto Uploader DRY_RUN")
    print(f"Time: {datetime.now(JST).strftime('%Y-%m-%d %H:%M JST')}")
    pool = load_safe_pool()
    print(f"content_pool: {'loaded' if pool else 'fallback'}")
    images = scan_local_images()
    if not images:
        print("No local images found for DRY_RUN")
        return 1
    image = sorted(images, key=lambda x: x["name"])[0]
    tags = generate_tags(image["name"])
    title = build_title(image["name"])
    img_url = file_url(image["local_path"])
    body = build_body(img_url, title, tags)
    # FANZAアフィリエイト記事（別記事）も合わせてプレビュー
    fanza_title, fanza_body, fanza_tags = build_fanza_article(img_url)
    combined_body = (
        body
        + '\n<hr style="border:2px dashed #ff4d6d; margin:40px 0;" />\n'
        + '<p style="text-align:center; color:#ff4d6d;"><strong>↓↓↓ 別記事として続けて投稿される FANZAアフィリエイト記事 ↓↓↓</strong></p>\n'
        + f'<h2>{html.escape(fanza_title)}</h2>\n'
        + fanza_body
    )
    write_dry_run_preview(title, combined_body, tags, image)
    print(f"Selected: {image['name']}")
    print(f"Tags: {', '.join(tags[:10])}...")
    print(f"FANZA article: {fanza_title}")
    print("DRY_RUN complete: skipped FC2 auth, image upload, post creation, and uploaded log update.")
    return 0


def parse_args():
    parser = argparse.ArgumentParser(description="FC2 Blog Auto Uploader")
    parser.add_argument("--dry-run", action="store_true", help="build a local preview without external calls")
    return parser.parse_args()


# ===== メイン =====

def main():
    args = parse_args()
    if args.dry_run or env_truthy(os.environ.get("DRY_RUN")):
        return run_dry_run()

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
        print("Error: GDRIVE_FOLDER_ID not set (DeviantArtと同じDriveフォルダIDを設定。旧GDRIVE_FOLDER_ID_FC2も可)")
        return 1

    print("FC2 Blog Auto Uploader (XML-RPC)")
    print(f"Time: {datetime.now(JST).strftime('%Y-%m-%d %H:%M JST')}")
    print()

    # FC2 Blog接続
    client = get_fc2_client()
    if not verify_credentials(client):
        # タイムアウトの場合は警告を出しつつ続行（直接アップロードを試みる）
        print("WARNING: verify_credentials failed, but attempting upload anyway (timeout may be transient)")
        print("Continuing with direct upload attempt...")

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

        # 4. FANZAアフィリエイト記事を別記事として続けて投稿
        try:
            fanza_title, fanza_body, fanza_tags = build_fanza_article(image_url)
            print(f"\nFANZA affiliate post: {fanza_title}")
            fanza_post_id = create_blog_post(
                client, fanza_title, fanza_body, fanza_tags,
                publish=True, categories=['FANZA'],
            )
            print(f"FANZA post created! ID: {fanza_post_id}")
        except xmlrpc.client.Fault as e:
            print(f"FANZA post XML-RPC error (main post OK): {e.faultCode} - {e.faultString}")
        except Exception as e:
            print(f"FANZA post failed (main post OK): {e}")

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

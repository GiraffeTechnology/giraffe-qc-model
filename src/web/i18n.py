"""i18n adapter seam for the Giraffe web shell (Session S1).

This module is the web-side adapter for the ``giraffe-language-skill`` seam
described in the S0 contracts. Feature sessions (S2-S6) depend on this seam
rather than re-implementing language handling per page. It centralizes:

  * the supported language set — English / Chinese / Japanese,
  * language resolution: persisted user selection -> device language ->
    English fallback,
  * persistence of a user's explicit selection (cookie-backed, edition
    agnostic, works before any login), and
  * the string table used by the shell (welcome / admin home / navigation /
    language settings).

Page-internal strings remain owned by each feature session; only shell-level
keys live here. Sessions resolve the active language with :func:`resolve_language`
and translate shell keys through the ``t`` callable injected by
:func:`template_globals`.
"""
from __future__ import annotations

from typing import Optional

from starlette.requests import Request
from starlette.responses import Response

# --- Supported languages ---------------------------------------------------

LANG_EN = "en"
LANG_ZH = "zh-CN"
LANG_JA = "ja"

#: Ordered tuple of the languages the shell supports.
SUPPORTED_LANGUAGES = (LANG_EN, LANG_ZH, LANG_JA)

#: English is the guaranteed fallback per the PRD (§11).
DEFAULT_LANGUAGE = LANG_EN

#: Cookie used to persist an explicit user selection across sessions/editions.
LANGUAGE_COOKIE = "giraffe_lang"

#: One year — the selection should feel permanent once chosen.
_COOKIE_MAX_AGE = 60 * 60 * 24 * 365

#: Native-name labels shown in the language switch.
LANGUAGE_LABELS = {
    LANG_EN: "English",
    LANG_ZH: "中文",
    LANG_JA: "日本語",
}


def normalize_language(code: Optional[str]) -> Optional[str]:
    """Map an arbitrary BCP-47-ish tag to a supported language, or ``None``.

    ``zh``/``zh-Hans``/``zh-CN``/``zh-TW`` -> ``zh-CN``; ``ja``/``ja-JP`` ->
    ``ja``; ``en``/``en-US`` -> ``en``. Anything else returns ``None`` so the
    caller can continue down the resolution chain.
    """
    if not code:
        return None
    normalized = code.strip().lower().replace("_", "-")
    if not normalized:
        return None
    primary = normalized.split("-", 1)[0]
    if primary == "zh":
        return LANG_ZH
    if primary == "ja":
        return LANG_JA
    if primary == "en":
        return LANG_EN
    return None


def device_language(accept_language: Optional[str]) -> Optional[str]:
    """Resolve the device language from an ``Accept-Language`` header.

    Respects ``q`` weights and falls back through the list until a supported
    language is found. Returns ``None`` when none match.
    """
    if not accept_language:
        return None
    parsed = []
    for index, part in enumerate(accept_language.split(",")):
        part = part.strip()
        if not part:
            continue
        tokens = part.split(";")
        tag = tokens[0].strip()
        quality = 1.0
        for token in tokens[1:]:
            token = token.strip()
            if token.startswith("q="):
                try:
                    quality = float(token[2:])
                except ValueError:
                    quality = 0.0
        parsed.append((quality, index, tag))
    # Highest quality first; ties broken by original order.
    parsed.sort(key=lambda item: (-item[0], item[1]))
    for _quality, _index, tag in parsed:
        resolved = normalize_language(tag)
        if resolved:
            return resolved
    return None


def resolve_language(request: Request) -> str:
    """Resolve the active language for a request.

    Order per PRD §11:

      1. persisted explicit selection (cookie, then session), then
      2. device language (``Accept-Language``), then
      3. English fallback.
    """
    persisted = normalize_language(request.cookies.get(LANGUAGE_COOKIE))
    if persisted:
        return persisted

    # Best-effort: a prior selection stored on the server session.
    try:
        session_lang = normalize_language(request.session.get("lang"))
    except (AssertionError, AttributeError):
        session_lang = None
    if session_lang:
        return session_lang

    from_device = device_language(request.headers.get("accept-language"))
    if from_device:
        return from_device

    return DEFAULT_LANGUAGE


def persist_language(response: Response, language: str) -> str:
    """Persist an explicit selection onto ``response`` and return it normalized."""
    resolved = normalize_language(language) or DEFAULT_LANGUAGE
    response.set_cookie(
        LANGUAGE_COOKIE,
        resolved,
        max_age=_COOKIE_MAX_AGE,
        path="/",
        samesite="lax",
    )
    return resolved


# --- Shell string table ----------------------------------------------------
#
# Only shell-level keys live here. Each entry maps a key to per-language text;
# a missing language falls back to English, and a missing key falls back to the
# key itself so nothing renders blank.

_STRINGS = {
    "app.title": {
        LANG_EN: "Giraffe QC",
        LANG_ZH: "长颈鹿质检",
        LANG_JA: "ジラフ QC",
    },
    "nav.home": {
        LANG_EN: "Home",
        LANG_ZH: "首页",
        LANG_JA: "ホーム",
    },
    "language.switch": {
        LANG_EN: "Language",
        LANG_ZH: "语言",
        LANG_JA: "言語",
    },
    # Welcome page
    "welcome.tagline": {
        LANG_EN: "Visual quality control, on device and in the cloud.",
        LANG_ZH: "端侧与云端的视觉质量控制。",
        LANG_JA: "デバイスとクラウドでのビジュアル品質管理。",
    },
    "welcome.administrator": {
        LANG_EN: "Administrator",
        LANG_ZH: "管理员",
        LANG_JA: "管理者",
    },
    "welcome.operator": {
        LANG_EN: "Operator",
        LANG_ZH: "操作员",
        LANG_JA: "オペレーター",
    },
    "welcome.administrator.hint": {
        LANG_EN: "Configure standards, models and workstations",
        LANG_ZH: "配置标准、模型与工位",
        LANG_JA: "基準・モデル・ワークステーションを設定",
    },
    "welcome.operator.hint": {
        LANG_EN: "Run inspections on the line",
        LANG_ZH: "在产线上执行检验",
        LANG_JA: "ラインで検査を実行",
    },
    # Admin home
    "admin.home.title": {
        LANG_EN: "Administration",
        LANG_ZH: "管理后台",
        LANG_JA: "管理",
    },
    "admin.home.subtitle": {
        LANG_EN: "Set up and monitor the quality control system.",
        LANG_ZH: "配置并监控质量控制系统。",
        LANG_JA: "品質管理システムを設定・監視します。",
    },
    # Cards
    "admin.card.studio.title": {
        LANG_EN: "Digital Inspector Studio",
        LANG_ZH: "数字质检工作室",
        LANG_JA: "デジタル検査スタジオ",
    },
    "admin.card.studio.desc": {
        LANG_EN: "Author inspection logic and train the QC model.",
        LANG_ZH: "编写检验逻辑并训练质检模型。",
        LANG_JA: "検査ロジックを作成し QC モデルを学習させます。",
    },
    "admin.card.samples.title": {
        LANG_EN: "Samples & Standards",
        LANG_ZH: "样品与标准",
        LANG_JA: "サンプルと基準",
    },
    "admin.card.samples.desc": {
        LANG_EN: "Manage reference samples, photos and requirements.",
        LANG_ZH: "管理参考样品、照片与要求。",
        LANG_JA: "参照サンプル・写真・要件を管理します。",
    },
    "admin.card.samples.count_label": {
        LANG_EN: "active samples",
        LANG_ZH: "个有效样品",
        LANG_JA: "件の有効サンプル",
    },
    "admin.card.workstations.title": {
        LANG_EN: "Workstations",
        LANG_ZH: "工位",
        LANG_JA: "ワークステーション",
    },
    "admin.card.workstations.desc": {
        LANG_EN: "Register and assign inspection workstations.",
        LANG_ZH: "注册并分配检验工位。",
        LANG_JA: "検査ワークステーションを登録・割り当てます。",
    },
    "admin.card.bundles.title": {
        LANG_EN: "Bundles",
        LANG_ZH: "捆绑包",
        LANG_JA: "バンドル",
    },
    "admin.card.bundles.desc": {
        LANG_EN: "Package standards and models for deployment.",
        LANG_ZH: "打包标准与模型以便部署。",
        LANG_JA: "基準とモデルを配布用にまとめます。",
    },
    "admin.card.results.title": {
        LANG_EN: "Results",
        LANG_ZH: "结果",
        LANG_JA: "結果",
    },
    "admin.card.results.desc": {
        LANG_EN: "Review inspection outcomes and history.",
        LANG_ZH: "查看检验结果与历史。",
        LANG_JA: "検査結果と履歴を確認します。",
    },
    # Sample & standards administrator workspace
    "sample.admin.title": {LANG_EN: "QC Sample Admin", LANG_ZH: "质检样品管理", LANG_JA: "QC サンプル管理"},
    "sample.list.title": {LANG_EN: "Samples", LANG_ZH: "样品", LANG_JA: "サンプル"},
    "sample.nav.studio": {LANG_EN: "Admin Studio", LANG_ZH: "管理工作室", LANG_JA: "管理スタジオ"},
    "sample.nav.visual_model": {LANG_EN: "Visual QC Model", LANG_ZH: "视觉质检模型", LANG_JA: "ビジュアル QC モデル"},
    "sample.nav.new": {LANG_EN: "+ New Sample", LANG_ZH: "+ 新建样品", LANG_JA: "+ 新規サンプル"},
    "sample.list.subtitle": {LANG_EN: "Sample library shared by Pad and Server editions.", LANG_ZH: "Pad 端与服务器端共享的样品库。", LANG_JA: "Pad とサーバーで共有するサンプルライブラリです。"},
    "sample.field.item_number": {LANG_EN: "Item Number", LANG_ZH: "物料编号", LANG_JA: "品目番号"},
    "sample.field.name": {LANG_EN: "Name", LANG_ZH: "名称", LANG_JA: "名称"},
    "sample.field.category": {LANG_EN: "Category", LANG_ZH: "类别", LANG_JA: "カテゴリ"},
    "sample.field.description": {LANG_EN: "Description", LANG_ZH: "描述", LANG_JA: "説明"},
    "sample.field.photos": {LANG_EN: "Photos", LANG_ZH: "照片", LANG_JA: "写真"},
    "sample.field.requirements": {LANG_EN: "Requirements", LANG_ZH: "检验要求", LANG_JA: "検査要件"},
    "sample.field.detection_points": {LANG_EN: "Detection Points", LANG_ZH: "检测点", LANG_JA: "検出ポイント"},
    "sample.field.code": {LANG_EN: "Code", LANG_ZH: "代码", LANG_JA: "コード"},
    "sample.field.title": {LANG_EN: "Title", LANG_ZH: "标题", LANG_JA: "タイトル"},
    "sample.field.label": {LANG_EN: "Label", LANG_ZH: "标签", LANG_JA: "ラベル"},
    "sample.field.severity": {LANG_EN: "Severity", LANG_ZH: "严重程度", LANG_JA: "重大度"},
    "sample.field.pass_criteria": {LANG_EN: "Pass Criteria", LANG_ZH: "合格标准", LANG_JA: "合格基準"},
    "sample.field.requirement_text": {LANG_EN: "Requirement Text", LANG_ZH: "要求内容", LANG_JA: "要件本文"},
    "sample.field.point_code": {LANG_EN: "Point Code", LANG_ZH: "检测点代码", LANG_JA: "ポイントコード"},
    "sample.field.roi": {LANG_EN: "ROI", LANG_ZH: "检测区域", LANG_JA: "ROI"},
    "sample.field.roi_json": {LANG_EN: "ROI JSON", LANG_ZH: "检测区域 JSON", LANG_JA: "ROI JSON"},
    "sample.action.edit": {LANG_EN: "Edit", LANG_ZH: "编辑", LANG_JA: "編集"},
    "sample.action.cancel": {LANG_EN: "Cancel", LANG_ZH: "取消", LANG_JA: "キャンセル"},
    "sample.action.archive": {LANG_EN: "Archive", LANG_ZH: "归档", LANG_JA: "アーカイブ"},
    "sample.action.create": {LANG_EN: "Create Sample", LANG_ZH: "创建样品", LANG_JA: "サンプルを作成"},
    "sample.action.create_first": {LANG_EN: "Create your first sample", LANG_ZH: "创建第一个样品", LANG_JA: "最初のサンプルを作成"},
    "sample.list.empty": {LANG_EN: "No samples yet.", LANG_ZH: "尚无样品。", LANG_JA: "サンプルはまだありません。"},
    "sample.new.title": {LANG_EN: "New Sample", LANG_ZH: "新建样品", LANG_JA: "新規サンプル"},
    "sample.placeholder.category": {LANG_EN: "e.g. artificial_flower", LANG_ZH: "例如：artificial_flower", LANG_JA: "例: artificial_flower"},
    "sample.placeholder.optional_description": {LANG_EN: "Optional description", LANG_ZH: "可选描述", LANG_JA: "任意の説明"},
    "sample.placeholder.item_number": {LANG_EN: "ITEM-FLOWER-001", LANG_ZH: "物料-花卉-001", LANG_JA: "ITEM-FLOWER-001"},
    "sample.placeholder.name": {LANG_EN: "Artificial Flower A", LANG_ZH: "仿真花 A", LANG_JA: "造花 A"},
    "sample.placeholder.requirement_title": {LANG_EN: "No visible stain", LANG_ZH: "无可见污渍", LANG_JA: "目立つ汚れなし"},
    "sample.placeholder.requirement_text": {LANG_EN: "Describe the requirement...", LANG_ZH: "请描述检验要求……", LANG_JA: "要件を説明してください…"},
    "sample.placeholder.pass_criteria": {LANG_EN: "No stain larger than 2 mm", LANG_ZH: "不得有大于 2 毫米的污渍", LANG_JA: "2 mm を超える汚れがないこと"},
    "sample.placeholder.point_label": {LANG_EN: "Front surface stain check", LANG_ZH: "正面表面污渍检查", LANG_JA: "前面の汚れ検査"},
    "sample.error.duplicate": {LANG_EN: "Item number '{item_number}' already exists.", LANG_ZH: "物料编号“{item_number}”已存在。", LANG_JA: "品目番号「{item_number}」は既に存在します。"},
    "sample.detail.archive_confirm": {LANG_EN: "Archive this sample? It will be hidden from search.", LANG_ZH: "确定归档此样品吗？归档后将不会出现在搜索结果中。", LANG_JA: "このサンプルをアーカイブしますか？検索結果に表示されなくなります。"},
    "sample.detail.standard_photos": {LANG_EN: "Standard Photos", LANG_ZH: "标准照片", LANG_JA: "標準写真"},
    "sample.detail.photo": {LANG_EN: "Photo", LANG_ZH: "照片", LANG_JA: "写真"},
    "sample.detail.uploaded_file": {LANG_EN: "(uploaded file)", LANG_ZH: "（已上传文件）", LANG_JA: "（アップロード済み）"},
    "sample.detail.photo_unavailable": {LANG_EN: "Photo unavailable", LANG_ZH: "照片不可用", LANG_JA: "写真を表示できません"},
    "sample.detail.primary": {LANG_EN: "PRIMARY", LANG_ZH: "主照片", LANG_JA: "メイン"},
    "sample.detail.set_primary": {LANG_EN: "Set Primary", LANG_ZH: "设为主照片", LANG_JA: "メインに設定"},
    "sample.detail.add_photo": {LANG_EN: "Add Photo", LANG_ZH: "添加照片", LANG_JA: "写真を追加"},
    "sample.detail.capture_usb": {LANG_EN: "USB Camera", LANG_ZH: "USB 摄像头", LANG_JA: "USB カメラ"},
    "sample.detail.upload_file": {LANG_EN: "Upload File", LANG_ZH: "上传文件", LANG_JA: "ファイルをアップロード"},
    "sample.detail.register_url": {LANG_EN: "Register URL / Path", LANG_ZH: "登记 URL / 路径", LANG_JA: "URL / パスを登録"},
    "sample.camera.source": {LANG_EN: "Camera source", LANG_ZH: "摄像头来源", LANG_JA: "カメラソース"},
    "sample.camera.default": {LANG_EN: "System default camera", LANG_ZH: "系统默认摄像头", LANG_JA: "システム既定のカメラ"},
    "sample.camera.start": {LANG_EN: "Start USB camera", LANG_ZH: "启动 USB 摄像头", LANG_JA: "USB カメラを開始"},
    "sample.camera.capture": {LANG_EN: "Capture standard sample", LANG_ZH: "拍摄标准样本", LANG_JA: "標準サンプルを撮影"},
    "sample.camera.stop": {LANG_EN: "Stop camera", LANG_ZH: "停止摄像头", LANG_JA: "カメラを停止"},
    "sample.camera.ready": {LANG_EN: "USB camera ready", LANG_ZH: "USB 摄像头已就绪", LANG_JA: "USB カメラ準備完了"},
    "sample.camera.denied": {LANG_EN: "Camera unavailable or permission denied:", LANG_ZH: "摄像头不可用或权限被拒绝：", LANG_JA: "カメラが利用できないか権限が拒否されました:"},
    "sample.camera.timeout": {LANG_EN: "Camera permission timed out. Allow camera access and retry.", LANG_ZH: "摄像头授权超时，请允许摄像头访问后重试。", LANG_JA: "カメラ権限がタイムアウトしました。アクセスを許可して再試行してください。"},
    "sample.camera.required": {LANG_EN: "Connect and start a USB camera first.", LANG_ZH: "请先连接并启动 USB 摄像头。", LANG_JA: "先に USB カメラを接続して開始してください。"},
    "sample.camera.captured": {LANG_EN: "Photo captured. Upload it?", LANG_ZH: "照片已拍摄，是否上传？", LANG_JA: "撮影しました。アップロードしますか？"},
    "sample.camera.capture_failed": {LANG_EN: "Capture failed:", LANG_ZH: "拍摄失败：", LANG_JA: "撮影に失敗しました:"},
    "sample.camera.confirm": {LANG_EN: "Upload this photo?", LANG_ZH: "是否上传这张照片？", LANG_JA: "この写真をアップロードしますか？"},
    "sample.camera.upload_yes": {LANG_EN: "Yes, upload", LANG_ZH: "是，上传", LANG_JA: "はい、アップロード"},
    "sample.camera.retake": {LANG_EN: "Retake", LANG_ZH: "重拍", LANG_JA: "撮り直す"},
    "sample.camera.uploading": {LANG_EN: "Uploading standard photo…", LANG_ZH: "正在上传标准照片……", LANG_JA: "標準写真をアップロード中…"},
    "sample.detail.image_file": {LANG_EN: "Image File", LANG_ZH: "图片文件", LANG_JA: "画像ファイル"},
    "sample.detail.image_url": {LANG_EN: "Image URL", LANG_ZH: "图片 URL", LANG_JA: "画像 URL"},
    "sample.detail.local_path": {LANG_EN: "Local Path", LANG_ZH: "本地路径", LANG_JA: "ローカルパス"},
    "sample.detail.angle": {LANG_EN: "Angle", LANG_ZH: "拍摄角度", LANG_JA: "角度"},
    "sample.detail.view_type": {LANG_EN: "View Type", LANG_ZH: "视图类型", LANG_JA: "ビュー種別"},
    "sample.detail.set_as_primary": {LANG_EN: "Set as primary", LANG_ZH: "设为主照片", LANG_JA: "メインに設定"},
    "sample.detail.roi_editor": {LANG_EN: "ROI Editor", LANG_ZH: "检测区域编辑器", LANG_JA: "ROI エディタ"},
    "sample.detail.roi_help": {LANG_EN: "Drag on the photo to draw a detection region. Coordinates are normalized (0–1). Click \"Paste from ROI Editor\" in the detection point form below.", LANG_ZH: "在照片上拖动以绘制检测区域。坐标已归一化为 0–1；然后在下方检测点表单中点击“从区域编辑器粘贴”。", LANG_JA: "写真上をドラッグして検出領域を描画します。座標は 0–1 に正規化されます。下の検出ポイントフォームで「ROI エディタから貼り付け」をクリックしてください。"},
    "sample.detail.primary_photo": {LANG_EN: "Primary photo", LANG_ZH: "主照片", LANG_JA: "メイン写真"},
    "sample.detail.roi_drag": {LANG_EN: "Drag on image above to generate...", LANG_ZH: "在上方图片拖动以生成……", LANG_JA: "上の画像をドラッグして生成…"},
    "sample.detail.inspection_requirements": {LANG_EN: "Inspection Requirements", LANG_ZH: "检验要求", LANG_JA: "検査要件"},
    "sample.detail.add_requirement": {LANG_EN: "Add Requirement", LANG_ZH: "添加检验要求", LANG_JA: "要件を追加"},
    "sample.detail.detection_points": {LANG_EN: "Detection Points", LANG_ZH: "检测点", LANG_JA: "検出ポイント"},
    "sample.detail.add_detection_point": {LANG_EN: "Add Detection Point", LANG_ZH: "添加检测点", LANG_JA: "検出ポイントを追加"},
    "sample.detail.sample_detection_hint": {
        LANG_EN: "Detection points are drafted and confirmed in the sample standard workbench above.",
        LANG_ZH: "检测点在上方样品标准工作室中生成草案并确认。",
        LANG_JA: "検出ポイントは上のサンプル標準ワークベンチで下書きし、確認します。",
    },
    "sample.authoring.title": {
        LANG_EN: "Sample standard workbench",
        LANG_ZH: "样品标准工作室",
        LANG_JA: "サンプル標準ワークベンチ",
    },
    "sample.authoring.subtitle": {
        LANG_EN: "Enter standards in natural language, import a process card, or upload a standard file. Review every draft before confirmation.",
        LANG_ZH: "使用自然语言、导入工艺卡或上传标准文件录入检测标准；每份草案均须审核后确认。",
        LANG_JA: "自然言語、工程カード、標準ファイルで検査標準を入力し、すべての草案を確認してください。",
    },
    "sample.authoring.placeholder": {
        LANG_EN: "Describe detection standards or checkpoints…",
        LANG_ZH: "描述检测标准或检测点……",
        LANG_JA: "検査標準または検出ポイントを入力…",
    },
    "sample.authoring.welcome": {
        LANG_EN: "Describe the checkpoints, or import a process card or standard file. The text assistant will produce a structured draft for your review.",
        LANG_ZH: "请描述检测点，或导入工艺卡/标准文件。文字助手会生成结构化草案供你审核。",
        LANG_JA: "検出ポイントを入力するか、工程カード／標準ファイルを取り込んでください。文字アシスタントが確認用の構造化草案を作成します。",
    },
    "sample.detail.paste_roi": {LANG_EN: "Paste from ROI Editor", LANG_ZH: "从区域编辑器粘贴", LANG_JA: "ROI エディタから貼り付け"},
    "sample.severity.minor": {LANG_EN: "minor", LANG_ZH: "轻微", LANG_JA: "軽微"},
    "sample.severity.major": {LANG_EN: "major", LANG_ZH: "严重", LANG_JA: "重大"},
    "sample.severity.critical": {LANG_EN: "critical", LANG_ZH: "致命", LANG_JA: "致命的"},
    "sample.validation.roi_fields": {LANG_EN: "ROI JSON must have x, y, w, h fields.", LANG_ZH: "检测区域 JSON 必须包含 x、y、w、h 字段。", LANG_JA: "ROI JSON には x、y、w、h フィールドが必要です。"},
    "sample.validation.invalid_json": {LANG_EN: "Invalid JSON:", LANG_ZH: "无效的 JSON：", LANG_JA: "無効な JSON:"},
    # Stub pages
    "stub.placeholder": {
        LANG_EN: "This area is coming soon.",
        LANG_ZH: "此功能即将上线。",
        LANG_JA: "この機能は近日公開予定です。",
    },
    # Language settings
    "settings.language.title": {
        LANG_EN: "Language",
        LANG_ZH: "语言",
        LANG_JA: "言語",
    },
    "settings.language.desc": {
        LANG_EN: "Choose the display language for the app.",
        LANG_ZH: "选择应用的显示语言。",
        LANG_JA: "アプリの表示言語を選択してください。",
    },
    "settings.language.save": {
        LANG_EN: "Save",
        LANG_ZH: "保存",
        LANG_JA: "保存",
    },
    # Admin Studio
    "studio.page.title": {
        LANG_EN: "Digital Inspector Admin Studio — Giraffe QC",
        LANG_ZH: "数字质检员工作室 — 长颈鹿质检",
        LANG_JA: "デジタル検査員スタジオ — Giraffe QC",
    },
    "studio.header.title": {
        LANG_EN: "Digital Inspector Admin Studio",
        LANG_ZH: "数字质检员工作室",
        LANG_JA: "デジタル検査員スタジオ",
    },
    "studio.nav.home": {LANG_EN: "Admin home", LANG_ZH: "管理首页", LANG_JA: "管理ホーム"},
    "studio.nav.workstations": {LANG_EN: "Workstations", LANG_ZH: "工作站", LANG_JA: "ワークステーション"},
    "studio.nav.bundles": {LANG_EN: "Standards", LANG_ZH: "标准包", LANG_JA: "標準"},
    "studio.nav.results": {LANG_EN: "Results", LANG_ZH: "质检结果", LANG_JA: "結果"},
    "studio.workflow.label": {LANG_EN: "Training and release workflow", LANG_ZH: "训练与发布流程", LANG_JA: "トレーニングとリリースのフロー"},
    "studio.workflow.title": {LANG_EN: "Train and Release a Digital Inspector", LANG_ZH: "训练并发布数字质检员", LANG_JA: "デジタル検査員をトレーニングして公開"},
    "studio.workflow.subtitle": {
        LANG_EN: "The standard is authored on the sample page; this workspace only trains, qualifies, and publishes it.",
        LANG_ZH: "标准在样品页面创建；本工作室仅负责训练、合格判定与发布。",
        LANG_JA: "標準はサンプルページで作成します。このワークスペースはトレーニング・合格判定・公開のみを行います。",
    },
    "studio.workflow.training": {LANG_EN: "1 Training", LANG_ZH: "1 训练", LANG_JA: "1 トレーニング"},
    "studio.workflow.publish": {LANG_EN: "2 Publish", LANG_ZH: "2 发布", LANG_JA: "2 公開"},
    "studio.workflow.install": {LANG_EN: "3 Install", LANG_ZH: "3 安装", LANG_JA: "3 インストール"},
    "sample.workflow.label": {LANG_EN: "Sample entry workflow", LANG_ZH: "样品录入流程", LANG_JA: "サンプル登録フロー"},
    "sample.workflow.title": {LANG_EN: "Enter a Sample Standard", LANG_ZH: "录入样品标准", LANG_JA: "サンプル標準を登録"},
    "sample.workflow.subtitle": {
        LANG_EN: "Capture the sample and confirm its detection points here; training and publish happen in the Studio.",
        LANG_ZH: "在此采集样品并确认检测点；训练与发布在数字质检工作室完成。",
        LANG_JA: "ここでサンプルを取得し検出点を確認します。トレーニングと公開はスタジオで行います。",
    },
    "sample.workflow.entry": {LANG_EN: "1 Sample entry", LANG_ZH: "1 样品录入", LANG_JA: "1 サンプル登録"},
    "sample.workflow.confirmation": {LANG_EN: "2 Detection point confirmation", LANG_ZH: "2 检测点确认", LANG_JA: "2 検出点の確認"},
    "studio.nav.qc_model": {
        LANG_EN: "Visual QC Model",
        LANG_ZH: "视觉质检模型",
        LANG_JA: "ビジュアル QC モデル",
    },
    "studio.nav.samples": {
        LANG_EN: "Sample Admin",
        LANG_ZH: "样品管理",
        LANG_JA: "サンプル管理",
    },
    "studio.left.title": {
        LANG_EN: "SKUs",
        LANG_ZH: "SKU 列表",
        LANG_JA: "SKU",
    },
    "studio.search.placeholder": {
        LANG_EN: "Search SKU / name...",
        LANG_ZH: "搜索 SKU / 名称...",
        LANG_JA: "SKU / 名前を検索...",
    },
    "studio.status.all": {
        LANG_EN: "All statuses",
        LANG_ZH: "全部状态",
        LANG_JA: "すべての状態",
    },
    # PRD SKU lifecycle states (§ SKU lifecycle) — keys must stay aligned with
    # src.db.sku_models.SKU_LIFECYCLE_STATES.
    "studio.status.draft": {
        LANG_EN: "Draft",
        LANG_ZH: "草稿",
        LANG_JA: "下書き",
    },
    "studio.status.needs_information": {
        LANG_EN: "Needs Information",
        LANG_ZH: "待补充信息",
        LANG_JA: "情報不足",
    },
    "studio.status.ready_for_review": {
        LANG_EN: "Ready for Review",
        LANG_ZH: "待审核",
        LANG_JA: "レビュー待ち",
    },
    "studio.status.confirmed": {
        LANG_EN: "Confirmed",
        LANG_ZH: "已确认",
        LANG_JA: "確認済み",
    },
    "studio.status.published": {
        LANG_EN: "Published",
        LANG_ZH: "已发布",
        LANG_JA: "公開済み",
    },
    "studio.status.installed": {
        LANG_EN: "Installed",
        LANG_ZH: "已安装",
        LANG_JA: "インストール済み",
    },
    "studio.status.needs_requalification": {
        LANG_EN: "Needs Requalification",
        LANG_ZH: "需重新认证",
        LANG_JA: "再認定が必要",
    },
    "studio.center.title": {
        LANG_EN: "Training and release",
        LANG_ZH: "训练与发布",
        LANG_JA: "トレーニングと公開",
    },
    "studio.center.training_scope": {
        LANG_EN: "Select a SKU to run reviewed training, qualification, publishing, and installation. Detection standards are managed with the sample.",
        LANG_ZH: "选择 SKU 后进行审核训练、合规判定、发布与安装。检测标准随样品管理。",
        LANG_JA: "SKU を選択し、レビュー付きトレーニング、認定、公開、インストールを行います。検査標準はサンプル側で管理します。",
    },
    "studio.center.open_sample": {
        LANG_EN: "Open sample standard workbench",
        LANG_ZH: "打开样品标准工作室",
        LANG_JA: "サンプル標準ワークベンチを開く",
    },
    "studio.voice.title": {
        LANG_EN: "Voice input",
        LANG_ZH: "语音输入",
        LANG_JA: "音声入力",
    },
    "studio.upload.title": {
        LANG_EN: "Upload standard photo",
        LANG_ZH: "上传标准照片",
        LANG_JA: "標準写真をアップロード",
    },
    "studio.album.title": {
        LANG_EN: "Choose standard sample from photo library",
        LANG_ZH: "从相册选择标准样本",
        LANG_JA: "写真ライブラリから標準サンプルを選択",
    },
    "studio.album.permission": {
        LANG_EN: "The system photo picker will request access. Only the photo you select can be read.",
        LANG_ZH: "即将打开系统相册并申请读取权限；应用只能读取你明确选择的照片。",
        LANG_JA: "システム写真選択画面でアクセスを確認します。選択した写真だけを読み取ります。",
    },
    "studio.album.unavailable": {
        LANG_EN: "Photo-library reading is unavailable in this browser.",
        LANG_ZH: "当前浏览器不支持读取相册照片。",
        LANG_JA: "このブラウザでは写真ライブラリを読み取れません。",
    },
    "studio.album.reading": {
        LANG_EN: "Checking whether the selected photo is readable…",
        LANG_ZH: "正在检查所选相册照片是否可读…",
        LANG_JA: "選択した写真を読み取れるか確認中…",
    },
    "studio.album.readable": {
        LANG_EN: "The selected photo is readable. Uploading the confirmed selection…",
        LANG_ZH: "所选照片可读，正在上传已确认的照片…",
        LANG_JA: "選択した写真を読み取れました。確認済み写真をアップロード中…",
    },
    "studio.album.unreadable": {
        LANG_EN: "The selected photo cannot be read and was not uploaded.",
        LANG_ZH: "所选照片不可读，未执行上传。",
        LANG_JA: "選択した写真を読み取れないため、アップロードしませんでした。",
    },
    "studio.file.title": {
        LANG_EN: "Upload standard sample from device folder",
        LANG_ZH: "从当前设备文件夹上传标准样本",
        LANG_JA: "端末フォルダから標準サンプルをアップロード",
    },
    "studio.file.unavailable": {
        LANG_EN: "Device-file reading is unavailable in this browser.",
        LANG_ZH: "当前浏览器不支持读取设备文件。",
        LANG_JA: "このブラウザでは端末ファイルを読み取れません。",
    },
    "studio.file.opening": {
        LANG_EN: "Opening this device's file folder. Select one image to upload.",
        LANG_ZH: "正在打开当前设备的文件夹，请选择一张图片上传。",
        LANG_JA: "この端末のフォルダを開きます。アップロードする画像を1枚選択してください。",
    },
    "studio.file.reading": {
        LANG_EN: "Checking whether the selected device file is readable…",
        LANG_ZH: "正在检查所选设备文件是否可读…",
        LANG_JA: "選択した端末ファイルを読み取れるか確認中…",
    },
    "studio.file.readable": {
        LANG_EN: "The selected device file is readable. Uploading…",
        LANG_ZH: "所选设备文件可读，正在上传…",
        LANG_JA: "選択した端末ファイルを読み取れました。アップロード中…",
    },
    "studio.file.unreadable": {
        LANG_EN: "The selected device file cannot be read and was not uploaded.",
        LANG_ZH: "所选设备文件不可读，未执行上传。",
        LANG_JA: "選択した端末ファイルを読み取れないため、アップロードしませんでした。",
    },
    "studio.camera.toggle": {
        LANG_EN: "Capture standard sample with USB camera",
        LANG_ZH: "使用 USB 摄像头采集标准样本",
        LANG_JA: "USB カメラで標準サンプルを撮影",
    },
    "studio.camera.heading": {
        LANG_EN: "Capture standard sample",
        LANG_ZH: "采集标准样本",
        LANG_JA: "標準サンプルを撮影",
    },
    "studio.camera.close": {LANG_EN: "Close camera", LANG_ZH: "关闭摄像头", LANG_JA: "カメラを閉じる"},
    "studio.camera.source": {LANG_EN: "Camera source", LANG_ZH: "摄像头来源", LANG_JA: "カメラソース"},
    "studio.camera.default": {LANG_EN: "System default camera", LANG_ZH: "系统默认摄像头", LANG_JA: "システム既定のカメラ"},
    "studio.camera.start": {LANG_EN: "Start USB camera", LANG_ZH: "启动 USB 摄像头", LANG_JA: "USB カメラを開始"},
    "studio.camera.capture": {LANG_EN: "Capture standard sample", LANG_ZH: "拍摄标准样本", LANG_JA: "標準サンプルを撮影"},
    "studio.camera.stop": {LANG_EN: "Stop camera", LANG_ZH: "停止摄像头", LANG_JA: "カメラを停止"},
    "studio.camera.ready": {LANG_EN: "USB camera ready", LANG_ZH: "USB 摄像头已就绪", LANG_JA: "USB カメラ準備完了"},
    "studio.camera.denied": {
        LANG_EN: "Camera unavailable or permission denied:",
        LANG_ZH: "摄像头不可用或权限被拒绝：",
        LANG_JA: "カメラを利用できないか、権限が拒否されました:",
    },
    "studio.camera.timeout": {
        LANG_EN: "Camera permission timed out. Allow camera access and retry.",
        LANG_ZH: "摄像头授权超时，请允许摄像头访问后重试。",
        LANG_JA: "カメラ権限がタイムアウトしました。アクセスを許可して再試行してください。",
    },
    "studio.camera.required": {
        LANG_EN: "Connect and start a USB camera first.",
        LANG_ZH: "请先连接并启动 USB 摄像头。",
        LANG_JA: "先に USB カメラを接続して開始してください。",
    },
    "studio.camera.captured": {
        LANG_EN: "Standard sample captured. Review the still image before uploading.",
        LANG_ZH: "标准样本已拍摄，请检查定格画面后再决定是否上传。",
        LANG_JA: "標準サンプルを撮影しました。アップロード前に静止画を確認してください。",
    },
    "studio.camera.capture_failed": {
        LANG_EN: "Standard-sample capture failed:",
        LANG_ZH: "标准样本采集失败：",
        LANG_JA: "標準サンプルの撮影に失敗しました:",
    },
    "studio.camera.confirm": {
        LANG_EN: "Upload this standard-sample photo?",
        LANG_ZH: "是否上传这张标准样本照片？",
        LANG_JA: "この標準サンプル写真をアップロードしますか？",
    },
    "studio.camera.upload_yes": {LANG_EN: "Yes, upload", LANG_ZH: "是，上传", LANG_JA: "はい、アップロード"},
    "studio.camera.retake": {LANG_EN: "Retake", LANG_ZH: "重拍", LANG_JA: "撮り直す"},
    "studio.camera.uploading": {
        LANG_EN: "Uploading the confirmed standard sample for live visual analysis…",
        LANG_ZH: "正在上传已确认的标准样本并进行实时视觉分析…",
        LANG_JA: "確認済み標準サンプルをアップロードし、ライブ画像分析を実行中…",
    },
    "studio.chat.placeholder": {
        LANG_EN: "Create a SKU or describe QC requirements...",
        LANG_ZH: "创建 SKU 或描述质检要求...",
        LANG_JA: "SKU を作成するか QC 要件を入力...",
    },
    "studio.import.toolbar": {LANG_EN: "Import QC standards", LANG_ZH: "导入质检标准", LANG_JA: "検査標準を取り込む"},
    "studio.import.process_card": {LANG_EN: "Import process card", LANG_ZH: "导入工艺卡", LANG_JA: "工程カードを取り込む"},
    "studio.import.file": {LANG_EN: "Upload standard file", LANG_ZH: "上传标准文件", LANG_JA: "標準ファイルをアップロード"},
    "studio.import.hint": {
        LANG_EN: "Graphic files: JPG / PNG / PDF. Images use OCR first; all text is structured by the text assistant.",
        LANG_ZH: "图形文件请使用 JPG / PNG / PDF；图片先进行 OCR，所有文本均由文字助手生成结构化草案。",
        LANG_JA: "画像ファイルは JPG / PNG / PDF。画像は先に OCR を行い、すべてのテキストを文字アシスタントが構造化します。",
    },
    "studio.js.select_before_import": {LANG_EN: "Select a SKU before importing standards.", LANG_ZH: "导入检测标准前，请先选择 SKU。", LANG_JA: "標準を取り込む前に SKU を選択してください。"},
    "studio.js.import_opening": {LANG_EN: "Opening the device file picker…", LANG_ZH: "正在打开当前设备文件夹…", LANG_JA: "端末のファイル選択画面を開いています…"},
    "studio.js.import_reading": {LANG_EN: "Importing {filename}", LANG_ZH: "正在导入 {filename}", LANG_JA: "{filename} を取り込み中"},
    "studio.js.import_sending": {
        LANG_EN: "Extracting the source and asking the text assistant to draft a structured standard…",
        LANG_ZH: "正在提取内容并交给文字助手生成结构化检测标准草案…",
        LANG_JA: "内容を抽出し、テキストアシスタントに構造化標準の草案作成を依頼しています…",
    },
    "studio.js.import_complete": {LANG_EN: "Structured draft ready for administrator review.", LANG_ZH: "结构化草案已生成，请管理员审核。", LANG_JA: "構造化草案が完成しました。管理者が確認してください。"},
    "studio.js.import_failed": {LANG_EN: "Standard import failed: {message}", LANG_ZH: "检测标准导入失败：{message}", LANG_JA: "標準の取り込みに失敗しました：{message}"},
    "studio.js.ocr_complete": {LANG_EN: "OCR completed; extracted text was passed to the text assistant.", LANG_ZH: "OCR 已完成，提取文本已交给文字助手。", LANG_JA: "OCR が完了し、抽出テキストをテキストアシスタントに渡しました。"},
    "studio.send": {
        LANG_EN: "Send",
        LANG_ZH: "发送",
        LANG_JA: "送信",
    },
    "studio.right.title": {
        LANG_EN: "Current standard",
        LANG_ZH: "当前质检标准",
        LANG_JA: "現在の標準",
    },
    "studio.human_gate": {
        LANG_EN: "Assistant output is a draft. Only your Confirm and Publish actions change the active standard.",
        LANG_ZH: "助手输出仅为草案；只有你点击“确认”和“发布”才会改变生效标准。",
        LANG_JA: "アシスタント出力は草案です。確認と公開の操作だけが有効な標準を変更します。",
    },
    "studio.assistant.checking": {LANG_EN: "Checking assistants…", LANG_ZH: "正在检查助手…", LANG_JA: "アシスタントを確認中…"},
    "studio.assistant.ready": {LANG_EN: "Text and vision ready", LANG_ZH: "文字与视觉助手已就绪", LANG_JA: "テキスト・画像準備完了"},
    "studio.assistant.unavailable": {LANG_EN: "Assistant configuration incomplete", LANG_ZH: "助手配置不完整", LANG_JA: "アシスタント設定が不完全"},
    "studio.assistant.text_thinking": {LANG_EN: "Text assistant is drafting…", LANG_ZH: "文字助手正在生成草案…", LANG_JA: "テキストアシスタントが作成中…"},
    "studio.assistant.vision_thinking": {LANG_EN: "Vision assistant is analyzing the photo…", LANG_ZH: "视觉助手正在分析照片…", LANG_JA: "画像アシスタントが分析中…"},
    "studio.assistant.meta": {LANG_EN: "Live · {model} · {seconds}s", LANG_ZH: "实时 · {model} · {seconds}秒", LANG_JA: "ライブ · {model} · {seconds}秒"},
    "studio.js.vision_failed": {LANG_EN: "Photo saved, but visual analysis failed: {message}", LANG_ZH: "照片已保存，但视觉分析失败：{message}", LANG_JA: "写真は保存されましたが画像分析に失敗しました：{message}"},
    "studio.lifecycle": {LANG_EN: "Lifecycle", LANG_ZH: "生命周期", LANG_JA: "ライフサイクル"},
    "studio.revision": {LANG_EN: "Revision", LANG_ZH: "修订版本", LANG_JA: "リビジョン"},
    "studio.confirmed_points": {LANG_EN: "Confirmed detection points", LANG_ZH: "已确认检测点", LANG_JA: "確認済み検査ポイント"},
    "studio.install.manage": {LANG_EN: "Manage install →", LANG_ZH: "管理安装 →", LANG_JA: "インストール管理 →"},
    "studio.install.next": {LANG_EN: "After publishing, assign this signed standard to a workstation.", LANG_ZH: "发布后，将签名标准分配并安装到工作站。", LANG_JA: "公開後、署名済み標準をワークステーションに割り当てます。"},
    "studio.engineering": {LANG_EN: "Advanced engineering settings", LANG_ZH: "高级工程设置", LANG_JA: "高度なエンジニア設定"},
    "studio.empty.standard": {
        LANG_EN: "Select or create a SKU to see its standard.",
        LANG_ZH: "选择或创建 SKU 以查看标准。",
        LANG_JA: "SKU を選択または作成して標準を表示します。",
    },
    "studio.confirm.head": {
        LANG_EN: "Candidate detection points",
        LANG_ZH: "候选检测点",
        LANG_JA: "候補検査ポイント",
    },
    "studio.confirm.yes": {
        LANG_EN: "Confirm & save",
        LANG_ZH: "确认并保存",
        LANG_JA: "確認して保存",
    },
    "studio.confirm.no": {
        LANG_EN: "Reject",
        LANG_ZH: "拒绝",
        LANG_JA: "却下",
    },
    "studio.js.no_skus": {
        LANG_EN: "No SKUs yet.",
        LANG_ZH: "还没有 SKU。",
        LANG_JA: "SKU はまだありません。",
    },
    "studio.js.no_photo": {
        LANG_EN: "No standard photo yet",
        LANG_ZH: "还没有标准照片",
        LANG_JA: "標準写真はまだありません",
    },
    "studio.js.standard_photo_alt": {
        LANG_EN: "standard photo",
        LANG_ZH: "标准照片",
        LANG_JA: "標準写真",
    },
    "studio.js.expected": {
        LANG_EN: "expected: {value}",
        LANG_ZH: "期望值：{value}",
        LANG_JA: "期待値: {value}",
    },
    "studio.js.no_detection_points": {
        LANG_EN: "No confirmed detection points.",
        LANG_ZH: "还没有已确认的检测点。",
        LANG_JA: "確認済み検査ポイントはありません。",
    },
    "studio.js.publish": {
        LANG_EN: "Publish to Pad (L2)",
        LANG_ZH: "发布到 Pad (L2)",
        LANG_JA: "Pad に公開 (L2)",
    },
    "studio.js.publishing": {
        LANG_EN: "Publishing...",
        LANG_ZH: "正在发布...",
        LANG_JA: "公開中...",
    },
    "studio.js.published": {
        LANG_EN: "Published signed L2 bundle for {item} - {count} detection point(s).",
        LANG_ZH: "已为 {item} 发布签名 L2 包 - {count} 个检测点。",
        LANG_JA: "{item} の署名済み L2 バンドルを公開しました - 検査ポイント {count} 件。",
    },
    "studio.js.bundle_note": {
        LANG_EN: "bundle {id} - {algorithm} - hash {hash}...",
        LANG_ZH: "包 {id} - {algorithm} - 哈希 {hash}...",
        LANG_JA: "バンドル {id} - {algorithm} - ハッシュ {hash}...",
    },
    "studio.js.publish_failed": {
        LANG_EN: "Publish failed: {message}",
        LANG_ZH: "发布失败：{message}",
        LANG_JA: "公開に失敗しました: {message}",
    },
    "studio.js.error": {
        LANG_EN: "Error: {message}",
        LANG_ZH: "错误：{message}",
        LANG_JA: "エラー: {message}",
    },
    "studio.js.expected_count_required": {
        LANG_EN: "Expected count required",
        LANG_ZH: "需要填写期望数量",
        LANG_JA: "期待数が必要です",
    },
    "studio.js.count_placeholder": {
        LANG_EN: "count",
        LANG_ZH: "数量",
        LANG_JA: "数",
    },
    "studio.js.provide_counts": {
        LANG_EN: "Please provide every expected count before confirming.",
        LANG_ZH: "确认前请填写所有期望数量。",
        LANG_JA: "確認前にすべての期待数を入力してください。",
    },
    "studio.js.resolve_questions_before_confirm": {
        LANG_EN: "Answer every outstanding question before confirming this draft.",
        LANG_ZH: "请先回答所有待补问题，再确认此草案。",
        LANG_JA: "未回答の質問にすべて回答してから、この下書きを確定してください。",
    },
    "studio.js.administrator_question": {
        LANG_EN: "Please provide the missing standard detail",
        LANG_ZH: "请补充缺失的质检标准信息",
        LANG_JA: "不足している検査基準の情報を入力してください",
    },
    "studio.js.answer_placeholder": {
        LANG_EN: "Answer",
        LANG_ZH: "请输入答案",
        LANG_JA: "回答を入力",
    },
    "studio.js.confirmed_revision": {
        LANG_EN: "Confirmed - revision {revision}.",
        LANG_ZH: "已确认 - 修订 {revision}。",
        LANG_JA: "確認済み - リビジョン {revision}。",
    },
    "studio.js.saved_points": {
        LANG_EN: "Saved {count} detection point(s) to revision {revision}. You can now publish to Pad.",
        LANG_ZH: "已将 {count} 个检测点保存到修订 {revision}。现在可以发布到 Pad。",
        LANG_JA: "{count} 件の検査ポイントをリビジョン {revision} に保存しました。Pad に公開できます。",
    },
    "studio.js.coverage_complete": {
        LANG_EN: "AI coverage self-review complete — verify the candidate list before confirmation.",
        LANG_ZH: "AI 已完成覆盖自审 — 确认前请审核候选列表。",
        LANG_JA: "AI の網羅性セルフレビューが完了しました — 確定前に候補一覧を確認してください。",
    },
    "studio.js.coverage_incomplete": {
        LANG_EN: "AI coverage self-review found unresolved visibility or standard gaps.",
        LANG_ZH: "AI 覆盖自审发现尚未解决的可见性或标准缺口。",
        LANG_JA: "AI の網羅性セルフレビューで未解決の視認性または基準の不足が見つかりました。",
    },
    "studio.js.coverage_checked": {
        LANG_EN: "Checked: {dimensions}", LANG_ZH: "已检查：{dimensions}", LANG_JA: "確認済み：{dimensions}",
    },
    "studio.js.coverage_omissions": {
        LANG_EN: "Needs clarification: {omissions}", LANG_ZH: "需要澄清：{omissions}", LANG_JA: "要確認：{omissions}",
    },
    "studio.js.rejected": {
        LANG_EN: "Rejected.",
        LANG_ZH: "已拒绝。",
        LANG_JA: "却下しました。",
    },
    "studio.js.select_before_upload": {
        LANG_EN: "Select or create a SKU before uploading a standard photo.",
        LANG_ZH: "上传标准照片前，请先选择或创建 SKU。",
        LANG_JA: "標準写真をアップロードする前に SKU を選択または作成してください。",
    },
    "studio.js.uploading_photo": {
        LANG_EN: "Uploading standard photo...",
        LANG_ZH: "正在上传标准照片...",
        LANG_JA: "標準写真をアップロード中...",
    },
    "studio.js.photo_uploaded": {
        LANG_EN: "Standard photo uploaded.",
        LANG_ZH: "标准照片已上传。",
        LANG_JA: "標準写真をアップロードしました。",
    },
    "studio.js.upload_failed": {
        LANG_EN: "Upload failed: {message}",
        LANG_ZH: "上传失败：{message}",
        LANG_JA: "アップロードに失敗しました: {message}",
    },
    "studio.js.voice_disabled": {
        LANG_EN: "Voice input is not enabled yet.",
        LANG_ZH: "语音输入尚未启用。",
        LANG_JA: "音声入力はまだ有効ではありません。",
    },
    "studio.js.welcome": {
        LANG_EN: "Tell me what product you want to inspect in natural language. I can create its SKU, read a reference photo, ask for missing counts or tolerances, and draft the detection points for your approval.",
        LANG_ZH: "请用自然语言告诉我你要质检什么产品。我可以创建 SKU、读取标准照片、追问缺少的数量或公差，并生成检测点草案供你审核。",
        LANG_JA: "検査する製品を自然な言葉で説明してください。SKU 作成、標準写真の確認、不足する数や公差の質問、検査ポイント草案の作成を支援します。",
    },
    "studio.region.photo": {LANG_EN: "Photo", LANG_ZH: "照片", LANG_JA: "写真"},
    "studio.region.hint": {
        LANG_EN: "Drag on the image to draw a box.", LANG_ZH: "在图片上拖动以绘制区域框。",
        LANG_JA: "画像上をドラッグして範囲を描画します。",
    },
    "studio.region.save": {LANG_EN: "Save regions", LANG_ZH: "保存区域", LANG_JA: "範囲を保存"},
    "studio.region.cancel": {LANG_EN: "Cancel", LANG_ZH: "取消", LANG_JA: "キャンセル"},
    "studio.js.regions": {LANG_EN: "Regions ({count})", LANG_ZH: "区域（{count}）", LANG_JA: "範囲（{count}）"},
    "studio.js.add_regions": {LANG_EN: "Add regions", LANG_ZH: "添加区域", LANG_JA: "範囲を追加"},
    "studio.js.edit_cv_config": {LANG_EN: "Edit CV config", LANG_ZH: "编辑 CV 配置", LANG_JA: "CV 設定を編集"},
    "studio.js.add_cv_config": {LANG_EN: "Add CV config", LANG_ZH: "添加 CV 配置", LANG_JA: "CV 設定を追加"},
    "studio.js.expected_features_prompt": {
        LANG_EN: 'Expected features JSON (example: {"rhinestone_count":24})',
        LANG_ZH: '期望特征 JSON（示例：{"rhinestone_count":24}）',
        LANG_JA: '期待特徴 JSON（例：{"rhinestone_count":24}）',
    },
    "studio.js.cv_config_prompt": {
        LANG_EN: "CV config JSON (analyzers: rhinestone_count, pearl_count, petal_segmentation, pistil_localization)",
        LANG_ZH: "CV 配置 JSON（分析器：rhinestone_count、pearl_count、petal_segmentation、pistil_localization）",
        LANG_JA: "CV 設定 JSON（アナライザー：rhinestone_count、pearl_count、petal_segmentation、pistil_localization）",
    },
    "studio.js.invalid_analysis_json": {
        LANG_EN: "Analysis config must be valid JSON: {message}", LANG_ZH: "分析配置必须是有效 JSON：{message}",
        LANG_JA: "分析設定は有効な JSON である必要があります：{message}",
    },
    "studio.js.analysis_saved": {LANG_EN: "Detection-point CV configuration saved.", LANG_ZH: "检测点 CV 配置已保存。", LANG_JA: "検査ポイントの CV 設定を保存しました。"},
    "studio.js.analysis_save_failed": {
        LANG_EN: "Could not save CV configuration: {message}", LANG_ZH: "无法保存 CV 配置：{message}",
        LANG_JA: "CV 設定を保存できませんでした：{message}",
    },
    "studio.js.probation_not_started": {LANG_EN: "Not yet on probation (publish to start).", LANG_ZH: "尚未进入试运行（发布后开始）。", LANG_JA: "試用期間は未開始です（公開すると開始）。"},
    "studio.js.probation_active": {LANG_EN: "On probation", LANG_ZH: "试运行中", LANG_JA: "試用期間中"},
    "studio.js.probation_paused": {LANG_EN: "Probation paused", LANG_ZH: "试运行已暂停", LANG_JA: "試用期間を一時停止中"},
    "studio.js.probation_qualified": {LANG_EN: "Qualified — solo", LANG_ZH: "已通过认证 — 可独立运行", LANG_JA: "認定済み — 単独運用"},
    "studio.js.probation_stats": {LANG_EN: "{jobs} job(s) · {rate}% agreement", LANG_ZH: "{jobs} 个任务 · 一致率 {rate}%", LANG_JA: "{jobs} 件 · 一致率 {rate}%"},
    "studio.js.probation_minimum": {LANG_EN: "(min {count} required)", LANG_ZH: "（至少需要 {count} 个）", LANG_JA: "（最低 {count} 件必要）"},
    "studio.js.pause": {LANG_EN: "Pause", LANG_ZH: "暂停", LANG_JA: "一時停止"},
    "studio.js.resume": {LANG_EN: "Resume", LANG_ZH: "继续", LANG_JA: "再開"},
    "studio.js.disagreement_report": {LANG_EN: "View disagreement report", LANG_ZH: "查看分歧报告", LANG_JA: "不一致レポートを表示"},
    "studio.js.probation_action_done": {LANG_EN: "Probation action completed: {action}.", LANG_ZH: "试运行操作已完成：{action}。", LANG_JA: "試用期間の操作が完了しました：{action}。"},
    "studio.js.probation_action_failed": {LANG_EN: "Could not {action} probation: {message}", LANG_ZH: "无法执行试运行操作 {action}：{message}", LANG_JA: "試用期間を {action} できませんでした：{message}"},
    "studio.js.no_disagreements": {LANG_EN: "No disagreements recorded yet — AI and human decisions have matched on every job so far.", LANG_ZH: "尚无分歧记录 — 目前每个任务的 AI 与人工判定均一致。", LANG_JA: "不一致はまだありません — 現時点では全ジョブで AI と人の判定が一致しています。"},
    "studio.js.disagreement_summary": {LANG_EN: "{count} disagreement(s) out of {jobs} job(s):", LANG_ZH: "{jobs} 个任务中有 {count} 个分歧：", LANG_JA: "{jobs} 件中 {count} 件の不一致："},
    "studio.js.disagreement_line": {LANG_EN: "  • {point}: {count} disagreement(s)", LANG_ZH: "  • {point}：{count} 个分歧", LANG_JA: "  • {point}：{count} 件の不一致"},
    "studio.js.disagreement_load_failed": {LANG_EN: "Could not load disagreement report: {message}", LANG_ZH: "无法加载分歧报告：{message}", LANG_JA: "不一致レポートを読み込めませんでした：{message}"},
    "studio.js.upload_photo_before_regions": {LANG_EN: "Upload a standard photo before adding regions.", LANG_ZH: "添加区域前请先上传标准照片。", LANG_JA: "範囲を追加する前に標準写真をアップロードしてください。"},
    "studio.js.primary": {LANG_EN: "primary", LANG_ZH: "主图", LANG_JA: "メイン"},
    "studio.js.remove": {LANG_EN: "Remove", LANG_ZH: "移除", LANG_JA: "削除"},
    "studio.js.regions_saved": {LANG_EN: "Saved {count} region(s) for {point}.", LANG_ZH: "已为 {point} 保存 {count} 个区域。", LANG_JA: "{point} に {count} 件の範囲を保存しました。"},
    "studio.js.training_heading": {LANG_EN: "Training", LANG_ZH: "训练", LANG_JA: "トレーニング"},
    "studio.js.training_qualified": {LANG_EN: "Training qualified", LANG_ZH: "训练已合规", LANG_JA: "トレーニング合格"},
    "studio.js.training_not_qualified": {LANG_EN: "Training not qualified", LANG_ZH: "训练未合规", LANG_JA: "トレーニング未合格"},
    "studio.js.training_window_stats": {LANG_EN: "Last {size}: {correct}/{size} correct", LANG_ZH: "最近 {size} 次：{correct}/{size} 正确", LANG_JA: "直近 {size} 件中 {correct}/{size} 件正解"},
    "studio.js.training_no_samples": {LANG_EN: "No reviewed training samples yet.", LANG_ZH: "尚无已裁决的训练样本。", LANG_JA: "レビュー済みのトレーニングサンプルはまだありません。"},
    "studio.js.training_false_pass": {LANG_EN: "{count} false pass(es) in the current window — this alone blocks qualification.", LANG_ZH: "当前窗口内有 {count} 次误判合格（False pass），仅此一项即阻止合规。", LANG_JA: "現在のウィンドウ内に {count} 件のフォールスパスがあり、これだけで合格を阻止します。"},
    "studio.js.training_ground_truth_qualified": {LANG_EN: "Sample is qualified", LANG_ZH: "样本为合格品", LANG_JA: "サンプルは合格品"},
    "studio.js.training_ground_truth_unqualified": {LANG_EN: "Sample is unqualified (staged defect)", LANG_ZH: "样本为不合格品（人为制造缺陷）", LANG_JA: "サンプルは不合格品（模擬欠陥）"},
    "studio.js.training_sample_source": {LANG_EN: "Training sample from Sample & Standard", LANG_ZH: "从样品与标准调用训练样本", LANG_JA: "サンプルと標準からトレーニングサンプルを選択"},
    "studio.js.training_submit_sample": {LANG_EN: "Run CV + VLM judgment", LANG_ZH: "运行 CV+VLM 判断", LANG_JA: "CV+VLM 判定を実行"},
    "studio.js.training_select_sample": {LANG_EN: "Select a labeled sample photo first.", LANG_ZH: "请先选择已标注真值的样本照片。", LANG_JA: "先にラベル付きサンプル写真を選択してください。"},
    "studio.js.training_running": {LANG_EN: "Running CV + VLM training judgment…", LANG_ZH: "正在运行 CV+VLM 训练判断……", LANG_JA: "CV+VLM トレーニング判定を実行中…"},
    "studio.js.training_recorded": {LANG_EN: "Training judgment recorded — awaiting your review.", LANG_ZH: "训练判断已记录，等待管理员裁决。", LANG_JA: "トレーニング判定を記録しました。レビュー待ちです。"},
    "studio.js.training_failed": {LANG_EN: "Training judgment failed: {message}", LANG_ZH: "训练判断失败：{message}", LANG_JA: "トレーニング判定に失敗しました：{message}"},
    "studio.js.training_queue_empty": {LANG_EN: "No training judgments awaiting review.", LANG_ZH: "没有待裁决的训练判断。", LANG_JA: "レビュー待ちのトレーニング判定はありません。"},
    "studio.js.training_ground_truth": {LANG_EN: "Ground truth: {label}", LANG_ZH: "真值：{label}", LANG_JA: "正解ラベル：{label}"},
    "studio.js.training_model_result": {LANG_EN: "Model said: {result}", LANG_ZH: "模型判断：{result}", LANG_JA: "モデル判定：{result}"},
    "studio.js.training_correct": {LANG_EN: "Judgment correct", LANG_ZH: "判断正确", LANG_JA: "判定は正しい"},
    "studio.js.training_incorrect": {LANG_EN: "Judgment incorrect", LANG_ZH: "判断不正确", LANG_JA: "判定は誤り"},
    "studio.js.training_correction_point": {LANG_EN: "Which checkpoint was wrong? (point_code)", LANG_ZH: "哪个检测点判断错误？（point_code）", LANG_JA: "どのチェックポイントが誤っていましたか？（point_code）"},
    "studio.js.training_correction_model_error": {LANG_EN: "What did the model get wrong?", LANG_ZH: "模型错在哪里？", LANG_JA: "モデルは何を間違えましたか？"},
    "studio.js.training_correction_conclusion": {LANG_EN: "What is the correct pass/fail conclusion?", LANG_ZH: "正确的合格/不合格结论是什么？", LANG_JA: "正しい合否結論は何ですか？"},
    "studio.js.training_correction_facts": {LANG_EN: "Correct facts / explanation", LANG_ZH: "正确事实或纠正说明", LANG_JA: "正しい事実・説明"},
    "studio.js.training_decision_saved": {LANG_EN: "Decision recorded.", LANG_ZH: "裁决已记录。", LANG_JA: "判定を記録しました。"},
    "studio.js.training_decision_failed": {LANG_EN: "Could not record decision: {message}", LANG_ZH: "无法记录裁决：{message}", LANG_JA: "判定を記録できませんでした：{message}"},
    "studio.js.publish_blocked_by_training": {
        LANG_EN: "Publish is blocked until the consecutive 30-sample window reaches at least 29 correct (>95%), covers qualified and unqualified samples, and has zero false passes.",
        LANG_ZH: "训练未合规前不得发布（连续 30 次中至少 29 次正确，即正确率 >95%；并覆盖合格与不合格样本，窗口内 False pass 为 0）。",
        LANG_JA: "直近30件中29件以上正解（95%超）、合格・不合格サンプルの両方を含み、フォールスパスがゼロになるまで公開できません。",
    },
    "studio.standard_status.no_standard": {LANG_EN: "No standard", LANG_ZH: "无标准", LANG_JA: "標準なし"},
    "studio.standard_status.standard_empty": {LANG_EN: "Standard empty", LANG_ZH: "标准为空", LANG_JA: "標準は空です"},
    "studio.standard_status.standard_active": {LANG_EN: "Standard active", LANG_ZH: "标准已启用", LANG_JA: "標準は有効です"},
    "security.mutation.label": {
        LANG_EN: "Sample authorization password/key",
        LANG_ZH: "样本操作鉴权密码/密钥",
        LANG_JA: "サンプル操作認証パスワード／キー",
    },
    "security.mutation.hint": {
        LANG_EN: "Required for this operation and must differ from your login credential.",
        LANG_ZH: "本次操作必须鉴权，且鉴权凭据不得与登录凭据相同。",
        LANG_JA: "この操作には認証が必要で、ログイン資格情報とは異なる必要があります。",
    },
    "security.mutation.required": {
        LANG_EN: "Enter the sample authorization password/key for this operation.",
        LANG_ZH: "请输入本次样本操作的鉴权密码/密钥。",
        LANG_JA: "このサンプル操作の認証パスワード／キーを入力してください。",
    },
    "security.publish.prompt": {
        LANG_EN: "Enter the separate sample publication password/key",
        LANG_ZH: "请输入独立的样本发布鉴权密码/密钥",
        LANG_JA: "別のサンプル公開認証パスワード／キーを入力してください",
    },
    # Admin login
    "admin.login.title": {
        LANG_EN: "Sign in — QC Admin",
        LANG_ZH: "登录 — 质检管理",
        LANG_JA: "サインイン — QC 管理",
    },
    "admin.login.heading": {
        LANG_EN: "Giraffe QC — Admin sign in",
        LANG_ZH: "长颈鹿质检 — 管理员登录",
        LANG_JA: "ジラフ QC — 管理者サインイン",
    },
    "admin.login.username": {
        LANG_EN: "Username",
        LANG_ZH: "用户名",
        LANG_JA: "ユーザー名",
    },
    "admin.login.password": {
        LANG_EN: "Password",
        LANG_ZH: "密码",
        LANG_JA: "パスワード",
    },
    "admin.login.tenant": {
        LANG_EN: "Tenant",
        LANG_ZH: "租户",
        LANG_JA: "テナント",
    },
    "admin.login.submit": {
        LANG_EN: "Sign in",
        LANG_ZH: "登录",
        LANG_JA: "サインイン",
    },
    "admin.login.invalid": {
        LANG_EN: "Invalid credentials or insufficient role",
        LANG_ZH: "凭据无效或权限不足",
        LANG_JA: "認証情報が無効か、権限が不足しています",
    },
    # Pad (legacy web pages) — shared
    "pad.brand": {
        LANG_EN: "Giraffe QC Pad",
        LANG_ZH: "长颈鹿质检 Pad",
        LANG_JA: "ジラフ QC Pad",
    },
    "pad.orientation": {
        LANG_EN: "Please rotate your device to landscape mode to use QC Pad.",
        LANG_ZH: "请将设备旋转至横屏模式以使用质检 Pad。",
        LANG_JA: "QC Pad を使用するには、デバイスを横向きにしてください。",
    },
    # Pad login
    "pad.login.title": {
        LANG_EN: "QC Pad Login",
        LANG_ZH: "质检 Pad 登录",
        LANG_JA: "QC Pad ログイン",
    },
    "pad.login.subtitle": {
        LANG_EN: "Factory Quality Control",
        LANG_ZH: "工厂质量控制",
        LANG_JA: "工場品質管理",
    },
    "pad.login.username": {
        LANG_EN: "Username",
        LANG_ZH: "用户名",
        LANG_JA: "ユーザー名",
    },
    "pad.login.password": {
        LANG_EN: "Password",
        LANG_ZH: "密码",
        LANG_JA: "パスワード",
    },
    "pad.login.submit": {
        LANG_EN: "Login",
        LANG_ZH: "登录",
        LANG_JA: "ログイン",
    },
    "pad.login.invalid": {
        LANG_EN: "Invalid credentials",
        LANG_ZH: "凭据无效",
        LANG_JA: "認証情報が無効です",
    },
    # Pad workspace
    "pad.workspace.title": {
        LANG_EN: "QC Pad Workspace",
        LANG_ZH: "质检 Pad 工作台",
        LANG_JA: "QC Pad ワークスペース",
    },
    "pad.workspace.logout": {
        LANG_EN: "Logout",
        LANG_ZH: "退出登录",
        LANG_JA: "ログアウト",
    },
    "pad.workspace.language": {
        LANG_EN: "Language:",
        LANG_ZH: "语言：",
        LANG_JA: "言語:",
    },
    "pad.workspace.chat_placeholder": {
        LANG_EN: "Type your message (English, Chinese or Japanese)...",
        LANG_ZH: "输入消息（支持中文、英文或日文）...",
        LANG_JA: "メッセージを入力（日本語・英語・中国語対応）...",
    },
    "pad.workspace.send": {
        LANG_EN: "Send",
        LANG_ZH: "发送",
        LANG_JA: "送信",
    },
    "pad.workspace.voice": {
        LANG_EN: "Voice",
        LANG_ZH: "语音",
        LANG_JA: "音声",
    },
    "pad.workspace.image": {
        LANG_EN: "Image",
        LANG_ZH: "图片",
        LANG_JA: "画像",
    },
    "pad.workspace.cards_placeholder": {
        LANG_EN: "Action cards will appear here after sending a message.",
        LANG_ZH: "发送消息后，操作卡片将显示在这里。",
        LANG_JA: "メッセージを送信すると、ここにアクションカードが表示されます。",
    },
    "pad.control.mock_banner": {
        LANG_EN: "NON-PRODUCTION MOCK — Stage 2 may use fixtures or a Mac USB camera; no Jetson hardware is connected.",
        LANG_ZH: "非生产模拟 — Stage 2 可使用测试图片或 Mac USB 摄像头；不接入 Jetson 真机。",
        LANG_JA: "非本番モック — Stage 2 は画像または Mac USB カメラを使用し、Jetson 実機には接続しません。",
    },
    "pad.control.title": {
        LANG_EN: "Start a real QC job",
        LANG_ZH: "启动真实质检任务",
        LANG_JA: "実際の QC ジョブを開始",
    },
    "pad.control.help": {
        LANG_EN: "Search an active SKU, create a database-backed job, upload simulated evidence, and run the fail-closed finalizer.",
        LANG_ZH: "搜索已启用 SKU，创建数据库任务，上传模拟证据，并运行失败关闭的最终判定器。",
        LANG_JA: "有効な SKU を検索し、DB ジョブを作成し、模擬証拠をアップロードしてフェイルクローズ判定を実行します。",
    },
    "pad.control.search_placeholder": {
        LANG_EN: "SKU number or name",
        LANG_ZH: "SKU 编号或名称",
        LANG_JA: "SKU 番号または名称",
    },
    "pad.control.search": {LANG_EN: "Search", LANG_ZH: "搜索", LANG_JA: "検索"},
    "pad.control.start": {LANG_EN: "Start QC job", LANG_ZH: "启动质检任务", LANG_JA: "QC ジョブ開始"},
    "pad.control.searching": {LANG_EN: "Searching…", LANG_ZH: "正在搜索…", LANG_JA: "検索中…"},
    "pad.control.no_skus": {
        LANG_EN: "No active SKU with a confirmed standard was found.",
        LANG_ZH: "未找到具有已确认标准的启用 SKU。",
        LANG_JA: "確認済み標準を持つ有効な SKU が見つかりません。",
    },
    "pad.control.starting": {LANG_EN: "Creating job…", LANG_ZH: "正在创建任务…", LANG_JA: "ジョブ作成中…"},
    "pad.control.error": {LANG_EN: "QC control error:", LANG_ZH: "质检控制错误：", LANG_JA: "QC 制御エラー:"},
    # Pad chat runtime (JS)
    "pad.js.confirm_standard": {
        LANG_EN: "Confirm Standard",
        LANG_ZH: "确认标准",
        LANG_JA: "標準を確認",
    },
    "pad.js.edit": {
        LANG_EN: "Edit",
        LANG_ZH: "编辑",
        LANG_JA: "編集",
    },
    "pad.js.reject": {
        LANG_EN: "Reject",
        LANG_ZH: "拒绝",
        LANG_JA: "却下",
    },
    "pad.js.confirm": {
        LANG_EN: "Confirm",
        LANG_ZH: "确认",
        LANG_JA: "確認",
    },
    "pad.js.standard_activated": {
        LANG_EN: "✓ Standard activated",
        LANG_ZH: "✓ 标准已生效",
        LANG_JA: "✓ 標準が有効になりました",
    },
    "pad.js.voice_transcript_hint": {
        LANG_EN: "Voice transcript — edit before sending:",
        LANG_ZH: "语音转写 — 发送前可编辑：",
        LANG_JA: "音声の書き起こし — 送信前に編集できます:",
    },
    "pad.js.send_transcript": {
        LANG_EN: "Send Transcript",
        LANG_ZH: "发送转写内容",
        LANG_JA: "書き起こしを送信",
    },
    "pad.js.stop": {
        LANG_EN: "Stop",
        LANG_ZH: "停止",
        LANG_JA: "停止",
    },
    "pad.js.standard_confirmation_required": {
        LANG_EN: "Standard Confirmation Required",
        LANG_ZH: "需要确认标准",
        LANG_JA: "標準の確認が必要です",
    },
    "pad.js.source_label": {
        LANG_EN: "Source:",
        LANG_ZH: "来源：",
        LANG_JA: "ソース:",
    },
    "pad.js.standard_rejected": {
        LANG_EN: "Standard rejected.",
        LANG_ZH: "已拒绝该标准。",
        LANG_JA: "標準を却下しました。",
    },
    "pad.js.no_reply": {
        LANG_EN: "No reply",
        LANG_ZH: "无回复",
        LANG_JA: "応答がありません",
    },
    "pad.js.error_prefix": {
        LANG_EN: "Error:",
        LANG_ZH: "错误：",
        LANG_JA: "エラー:",
    },
    "pad.js.standard_confirmed_prefix": {
        LANG_EN: "Standard confirmed. Revision ID:",
        LANG_ZH: "标准已确认。修订 ID：",
        LANG_JA: "標準を確認しました。リビジョン ID:",
    },
    "pad.js.confirm_failed_prefix": {
        LANG_EN: "Confirmation failed:",
        LANG_ZH: "确认失败：",
        LANG_JA: "確認に失敗しました:",
    },
    "pad.js.unknown_error": {
        LANG_EN: "unknown error",
        LANG_ZH: "未知错误",
        LANG_JA: "不明なエラー",
    },
    "pad.js.voice_not_supported": {
        LANG_EN: "Voice input not supported in this browser.",
        LANG_ZH: "当前浏览器不支持语音输入。",
        LANG_JA: "このブラウザは音声入力に対応していません。",
    },
    # Pad inspection
    "pad.inspection.title": {
        LANG_EN: "QC Pad Inspection",
        LANG_ZH: "质检 Pad 检验",
        LANG_JA: "QC Pad 検査",
    },
    "pad.inspection.back": {
        LANG_EN: "Back to Workspace",
        LANG_ZH: "返回工作台",
        LANG_JA: "ワークスペースへ戻る",
    },
    "pad.inspection.heading": {
        LANG_EN: "Inspection Job #{id}",
        LANG_ZH: "检验任务 #{id}",
        LANG_JA: "検査ジョブ #{id}",
    },
    "pad.inspection.checkpoints": {
        LANG_EN: "Checkpoints",
        LANG_ZH: "检查点",
        LANG_JA: "チェックポイント",
    },
    "pad.inspection.loading": {
        LANG_EN: "Loading checkpoints...",
        LANG_ZH: "正在加载检查点...",
        LANG_JA: "チェックポイントを読み込み中...",
    },
    "pad.inspection.submit": {
        LANG_EN: "Submit Results",
        LANG_ZH: "提交结果",
        LANG_JA: "結果を送信",
    },
    "pad.inspection.view_report": {
        LANG_EN: "View Report",
        LANG_ZH: "查看报告",
        LANG_JA: "レポートを表示",
    },
    "pad.inspection.mock_banner": {
        LANG_EN: "NON-PRODUCTION MOCK — Stage 2 Mac capture only; real Jetson hardware starts in Stage 3.",
        LANG_ZH: "非生产模拟 — Stage 2 仅使用 Mac 采集；真实 Jetson 硬件从 Stage 3 开始。",
        LANG_JA: "非本番モック — Stage 2 は Mac 収録のみです。Jetson 実機は Stage 3 から開始します。",
    },
    "pad.inspection.evidence": {LANG_EN: "Reference and live sample", LANG_ZH: "标准照片与实时取样", LANG_JA: "基準写真とライブサンプル"},
    "pad.inspection.standard_photo": {
        LANG_EN: "Standard photo",
        LANG_ZH: "标准照片",
        LANG_JA: "標準写真",
    },
    "pad.inspection.live_sample": {
        LANG_EN: "Live sample video",
        LANG_ZH: "实时取样视频流",
        LANG_JA: "ライブサンプル映像",
    },
    "pad.inspection.no_standard_photo": {
        LANG_EN: "No confirmed standard photo is available.",
        LANG_ZH: "尚无可用的已确认标准照片。",
        LANG_JA: "確認済みの標準写真がありません。",
    },
    "pad.inspection.instance_searching": {
        LANG_EN: "CV is looking for a stable instance in the live video…",
        LANG_ZH: "CV 正在实时视频中寻找稳定实例……",
        LANG_JA: "CV がライブ映像から安定した個体を検出中…",
    },
    "pad.inspection.instance_progress": {
        LANG_EN: "Instance detected ({count}/2 stable frames)",
        LANG_ZH: "已识别实例（稳定帧 {count}/2）",
        LANG_JA: "個体を検出しました（安定フレーム {count}/2）",
    },
    "pad.inspection.instance_captured": {
        LANG_EN: "Stable instance detected. Capturing and judging automatically…",
        LANG_ZH: "已稳定识别实例，正在自动拍摄并判别……",
        LANG_JA: "安定した個体を検出しました。自動撮影・判定中…",
    },
    "pad.inspection.auto_failed": {
        LANG_EN: "Automatic CV capture failed:",
        LANG_ZH: "CV 自动拍摄失败：",
        LANG_JA: "CV 自動撮影に失敗しました：",
    },
    "pad.inspection.upload": {LANG_EN: "Upload fixture", LANG_ZH: "上传测试图片", LANG_JA: "テスト画像をアップロード"},
    "pad.inspection.camera_start": {LANG_EN: "Start USB camera", LANG_ZH: "启动 USB 摄像头", LANG_JA: "USB カメラを開始"},
    "pad.inspection.camera_source": {LANG_EN: "Camera source", LANG_ZH: "摄像头来源", LANG_JA: "カメラ入力"},
    "pad.inspection.camera_default": {LANG_EN: "System default camera", LANG_ZH: "系统默认摄像头", LANG_JA: "システム既定のカメラ"},
    "pad.inspection.camera_capture": {LANG_EN: "Capture and attach", LANG_ZH: "拍照并绑定", LANG_JA: "撮影して添付"},
    "pad.inspection.camera_stop": {LANG_EN: "Stop camera", LANG_ZH: "停止摄像头", LANG_JA: "カメラを停止"},
    "pad.inspection.camera_ready": {LANG_EN: "USB camera ready", LANG_ZH: "USB 摄像头已就绪", LANG_JA: "USB カメラ準備完了"},
    "pad.inspection.camera_required": {LANG_EN: "Connect and start a USB camera first.", LANG_ZH: "请先连接并启动 USB 摄像头。", LANG_JA: "先に USB カメラを接続して開始してください。"},
    "pad.inspection.camera_denied": {LANG_EN: "Camera unavailable or permission denied:", LANG_ZH: "摄像头不可用或权限被拒绝：", LANG_JA: "カメラが利用できないか権限が拒否されました:"},
    "pad.inspection.camera_timeout": {
        LANG_EN: "Camera permission timed out. Allow camera access in the browser and retry.",
        LANG_ZH: "摄像头授权超时。请在浏览器中允许摄像头访问后重试。",
        LANG_JA: "カメラ権限がタイムアウトしました。ブラウザーで許可して再試行してください。",
    },
    "pad.inspection.no_media": {LANG_EN: "No evidence attached", LANG_ZH: "尚未绑定证据", LANG_JA: "証拠は未添付です"},
    "pad.inspection.media_attached": {LANG_EN: "Evidence attached", LANG_ZH: "证据已绑定", LANG_JA: "証拠を添付しました"},
    "pad.inspection.vision_run": {
        LANG_EN: "Run live vision inspection",
        LANG_ZH: "运行实时视觉质检",
        LANG_JA: "ライブ画像検査を実行",
    },
    "pad.inspection.vision_analyzing": {
        LANG_EN: "Running live vision inspection…",
        LANG_ZH: "正在运行实时视觉质检…",
        LANG_JA: "ライブ画像検査を実行中…",
    },
    "pad.inspection.vision_ready": {
        LANG_EN: "Live vision suggestions are ready; review every checkpoint before submitting.",
        LANG_ZH: "实时视觉建议已生成；提交前请逐项审核。",
        LANG_JA: "ライブ画像検査の提案が生成されました。送信前に各項目を確認してください。",
    },
    "pad.inspection.vision_suggestion": {
        LANG_EN: "Live model suggestion",
        LANG_ZH: "实时模型建议",
        LANG_JA: "ライブモデル提案",
    },
    "pad.inspection.vision_failed": {
        LANG_EN: "Vision inspection failed closed:",
        LANG_ZH: "视觉质检失败并已关闭放行：",
        LANG_JA: "画像検査に失敗し、フェイルクローズしました:",
    },
    "pad.inspection.choose_result": {LANG_EN: "Choose result", LANG_ZH: "选择结果", LANG_JA: "結果を選択"},
    "pad.inspection.result.pass": {LANG_EN: "Pass", LANG_ZH: "合格", LANG_JA: "合格"},
    "pad.inspection.result.fail": {LANG_EN: "Fail", LANG_ZH: "不合格", LANG_JA: "不合格"},
    "pad.inspection.result.not_visible": {LANG_EN: "Not visible", LANG_ZH: "不可见", LANG_JA: "確認不可"},
    "pad.inspection.result.low_confidence": {LANG_EN: "Low confidence", LANG_ZH: "低置信度", LANG_JA: "低信頼度"},
    "pad.inspection.submit_help": {
        LANG_EN: "Every checkpoint is required. Missing or uncertain evidence can never silently pass.",
        LANG_ZH: "每个检查点都必须填写；缺失或不确定证据绝不会静默放行。",
        LANG_JA: "全チェックポイントが必須です。欠落・不確実な証拠が黙って合格になることはありません。",
    },
    "pad.inspection.incomplete": {LANG_EN: "Select a result for every checkpoint.", LANG_ZH: "请为每个检查点选择结果。", LANG_JA: "全チェックポイントの結果を選択してください。"},
    "pad.inspection.finalizing": {LANG_EN: "Saving results and finalizing…", LANG_ZH: "正在保存结果并完成判定…", LANG_JA: "結果を保存して判定中…"},
    "pad.inspection.finalized": {LANG_EN: "Final verdict:", LANG_ZH: "最终判定：", LANG_JA: "最終判定:"},
    "pad.inspection.error": {LANG_EN: "Inspection error:", LANG_ZH: "检验错误：", LANG_JA: "検査エラー:"},
    # Pad report
    "pad.report.title": {
        LANG_EN: "QC Pad Report",
        LANG_ZH: "质检 Pad 报告",
        LANG_JA: "QC Pad レポート",
    },
    "pad.report.back": {
        LANG_EN: "Back to Inspection",
        LANG_ZH: "返回检验",
        LANG_JA: "検査へ戻る",
    },
    "pad.report.heading": {
        LANG_EN: "Inspection Report #{id}",
        LANG_ZH: "检验报告 #{id}",
        LANG_JA: "検査レポート #{id}",
    },
    "pad.report.summary": {
        LANG_EN: "Report Summary",
        LANG_ZH: "报告摘要",
        LANG_JA: "レポート概要",
    },
    "pad.report.loading": {
        LANG_EN: "Loading report data...",
        LANG_ZH: "正在加载报告数据...",
        LANG_JA: "レポートデータを読み込み中...",
    },
    "pad.report.not_ready": {
        LANG_EN: "This inspection has not been finalized yet.",
        LANG_ZH: "该检验尚未完成最终判定。",
        LANG_JA: "この検査はまだ最終判定されていません。",
    },
    "pad.report.verdict": {LANG_EN: "Final verdict", LANG_ZH: "最终判定", LANG_JA: "最終判定"},
    "pad.report.job_status": {LANG_EN: "Job status", LANG_ZH: "任务状态", LANG_JA: "ジョブ状態"},
    "pad.report.evidence_count": {LANG_EN: "Evidence files", LANG_ZH: "证据文件", LANG_JA: "証拠ファイル"},
    "pad.report.checkpoints": {LANG_EN: "Checkpoint results", LANG_ZH: "检查点结果", LANG_JA: "チェックポイント結果"},
    "pad.report.error": {LANG_EN: "Report error:", LANG_ZH: "报告错误：", LANG_JA: "レポートエラー:"},
    "pad.report.legend.pass": {
        LANG_EN: "PASS = Green",
        LANG_ZH: "合格 = 绿色",
        LANG_JA: "合格 = 緑",
    },
    "pad.report.legend.fail": {
        LANG_EN: "FAIL = Red",
        LANG_ZH: "不合格 = 红色",
        LANG_JA: "不合格 = 赤",
    },
    "pad.report.legend.review": {
        LANG_EN: "REVIEW REQUIRED = Amber",
        LANG_ZH: "需复核 = 琥珀色",
        LANG_JA: "要レビュー = 琥珀色",
    },
}


def translate(key: str, language: str) -> str:
    """Translate a shell key for ``language`` with English/key fallback."""
    entry = _STRINGS.get(key)
    if entry is None:
        return key
    return entry.get(language) or entry.get(DEFAULT_LANGUAGE) or key


def _request_language(request) -> str:
    """Resolve (and cache per-request) the active language for a request."""
    if request is None:
        return DEFAULT_LANGUAGE
    state = getattr(request, "state", None)
    cached = getattr(state, "_giraffe_lang", None)
    if cached:
        return cached
    language = resolve_language(request)
    try:
        request.state._giraffe_lang = language
    except Exception:
        pass
    return language


def install_i18n(templates) -> None:
    """Register context-aware i18n globals on a ``Jinja2Templates`` env.

    Every shell template (and the shared ``base.html`` language switch) resolves
    language and translates through these globals, so pages need not thread i18n
    values through their render context — only ``request`` (which FastAPI already
    injects). Call once per router that should carry the language switch.

    Registers:
      * ``t(key)`` — translate a shell key in the request's language,
      * ``current_language()`` — the resolved language code,
      * ``supported_languages`` — ordered list of language codes,
      * ``language_labels`` — code -> native label mapping.
    """
    from jinja2 import pass_context

    env = templates.env

    @pass_context
    def _t(context, key: str) -> str:
        return translate(key, _request_language(context.get("request")))

    @pass_context
    def _current_language(context) -> str:
        return _request_language(context.get("request"))

    env.globals["t"] = _t
    env.globals["current_language"] = _current_language
    env.globals["supported_languages"] = list(SUPPORTED_LANGUAGES)
    env.globals["language_labels"] = LANGUAGE_LABELS

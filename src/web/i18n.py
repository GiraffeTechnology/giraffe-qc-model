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

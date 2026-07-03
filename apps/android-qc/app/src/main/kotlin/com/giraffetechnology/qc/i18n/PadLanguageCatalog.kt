package com.giraffetechnology.qc.i18n

import com.giraffetechnology.qc.contracts.GiraffeLanguageSkill

/**
 * Pad string catalog for the `giraffe-language-skill` seam.
 *
 * English ([EN]) is the canonical key set — its values are the exact,
 * spec-mandated operator-facing strings (S5 §8.1 task-selection messages, S6
 * §8.3 runtime-readiness messages). Other locales provide the same keys where
 * translated; any gap falls back to English via [InMemoryLanguageSkill] and,
 * finally, to the key itself. No user-facing string is hard-coded in a screen.
 *
 * Only the Pad-facing subset of the S0 `contracts/i18n/en.json` key set is
 * mirrored here (the keys the Pad edition actually renders), plus the Pad-only
 * `welcome.*`, `pad.task.*`, `pad.work.*`, `readiness.*`, `pad.review.*`, and
 * `pad.sync.*` groups introduced by S5/S6.
 */
object PadLanguageCatalog {

    val EN: Map<String, String> = mapOf(
        // ── shared / inherited from S0 en.json ─────────────────────────────
        "common.confirm" to "Confirm",
        "common.cancel" to "Cancel",
        "common.retry" to "Retry",
        "common.search" to "Search",
        "common.loading" to "Loading…",
        "common.error_generic" to "Something went wrong. Please try again.",
        "verdict.pass" to "Pass",
        "verdict.fail" to "Fail",
        "verdict.review_required" to "Review Required",

        // ── welcome (S5 §3.1) ──────────────────────────────────────────────
        "welcome.title" to "Giraffe QC",
        "welcome.subtitle" to "On-device factory quality control",
        "welcome.administrator" to "Administrator",
        "welcome.operator" to "Operator",
        "welcome.language" to "Language",

        // ── operator task selection (S5 §8.1) ──────────────────────────────
        "pad.task.title" to "Select QC Task",
        "pad.task.search_placeholder" to "Search installed SKUs…",
        "pad.task.offline_note" to "Offline — searching standards installed on this Pad.",
        "pad.task.confirm" to "Confirm SKU",
        // EXACT spec strings — do not reword.
        "pad.task.no_standards_installed" to
            "No standards installed. Please ask Administrator to publish or sync a standard bundle.",
        "pad.task.sku_not_found" to
            "SKU not found in installed standards. Please sync with Administrator.",

        // ── QC work page (S6 §8.2) ─────────────────────────────────────────
        "pad.work.title" to "QC Work",
        "pad.work.reference" to "Standard reference",
        "pad.work.log" to "Inspection log",
        "pad.work.input_hint" to "Type a message…",
        "pad.work.send" to "Send",
        "pad.work.voice" to "Voice",
        "pad.work.text" to "Text",
        "pad.work.capture" to "Capture",

        // ── runtime readiness (S6 §8.3) — EXACT spec strings ───────────────
        "readiness.mnn_native_ready_model_pending" to "MNN native ready; model pending",
        "readiness.model_ready" to "Model ready",
        "readiness.local_runtime_not_ready" to "Local runtime not ready",
        "readiness.no_standard_installed" to "No standard installed",
        "readiness.no_sku_selected" to "No SKU selected",
        "readiness.offline" to "Offline",
        "readiness.online" to "Online",

        // ── result review + submission (S6 §9) ─────────────────────────────
        "pad.review.title" to "Review Result",
        "pad.review.confirm_pass" to "Confirm Accept",
        "pad.review.confirm_fail" to "Confirm Reject",
        "pad.review.mark_review" to "Send for Review",
        "pad.review.submit" to "Submit Result",
        "pad.review.submitted" to "Result queued for sync.",
        "pad.review.standard_revision" to "Standard revision: {rev}",
        "pad.review.bundle_version" to "Bundle version: {ver}",

        // ── sync status (S6) ───────────────────────────────────────────────
        "pad.sync.title" to "Sync Status",
        "pad.sync.pending" to "{count} result(s) pending upload",
        "pad.sync.none_pending" to "All results uploaded.",
        "pad.sync.upload_now" to "Upload Now",
        "pad.sync.online" to "Online",
        "pad.sync.offline" to "Offline",
    )

    val ZH_CN: Map<String, String> = mapOf(
        "common.confirm" to "确认",
        "common.cancel" to "取消",
        "common.retry" to "重试",
        "common.search" to "搜索",
        "common.loading" to "加载中…",
        "verdict.pass" to "通过",
        "verdict.fail" to "不通过",
        "verdict.review_required" to "需人工复核",

        "welcome.title" to "Giraffe 质检",
        "welcome.subtitle" to "端侧工厂质量检测",
        "welcome.administrator" to "管理员",
        "welcome.operator" to "操作员",
        "welcome.language" to "语言",

        "pad.task.title" to "选择质检任务",
        "pad.task.search_placeholder" to "搜索已安装的 SKU…",
        "pad.task.offline_note" to "离线 — 正在搜索本 Pad 已安装的标准。",
        "pad.task.confirm" to "确认 SKU",
        "pad.task.no_standards_installed" to "尚未安装任何标准。请联系管理员发布或同步标准包。",
        "pad.task.sku_not_found" to "在已安装标准中未找到该 SKU。请与管理员同步。",

        "pad.work.title" to "质检工作",
        "pad.work.reference" to "标准参考图",
        "pad.work.log" to "检测记录",
        "pad.work.input_hint" to "输入消息…",
        "pad.work.send" to "发送",
        "pad.work.voice" to "语音",
        "pad.work.text" to "文本",
        "pad.work.capture" to "拍照",

        "readiness.mnn_native_ready_model_pending" to "MNN 原生就绪；模型待加载",
        "readiness.model_ready" to "模型就绪",
        "readiness.local_runtime_not_ready" to "本地运行时未就绪",
        "readiness.no_standard_installed" to "未安装标准",
        "readiness.no_sku_selected" to "未选择 SKU",
        "readiness.offline" to "离线",
        "readiness.online" to "在线",

        "pad.review.title" to "复核结果",
        "pad.review.confirm_pass" to "确认合格",
        "pad.review.confirm_fail" to "确认不合格",
        "pad.review.mark_review" to "转人工复核",
        "pad.review.submit" to "提交结果",
        "pad.review.submitted" to "结果已加入同步队列。",
        "pad.review.standard_revision" to "标准版本：{rev}",
        "pad.review.bundle_version" to "标准包版本：{ver}",

        "pad.sync.title" to "同步状态",
        "pad.sync.pending" to "有 {count} 条结果待上传",
        "pad.sync.none_pending" to "全部结果已上传。",
        "pad.sync.upload_now" to "立即上传",
        "pad.sync.online" to "在线",
        "pad.sync.offline" to "离线",
    )

    val JA: Map<String, String> = mapOf(
        "common.confirm" to "確認",
        "common.cancel" to "キャンセル",
        "common.retry" to "再試行",
        "common.search" to "検索",
        "common.loading" to "読み込み中…",
        "verdict.pass" to "合格",
        "verdict.fail" to "不合格",
        "verdict.review_required" to "要人手確認",

        "welcome.title" to "Giraffe QC",
        "welcome.subtitle" to "オンデバイス工場品質検査",
        "welcome.administrator" to "管理者",
        "welcome.operator" to "オペレーター",
        "welcome.language" to "言語",

        "pad.task.title" to "検査タスクを選択",
        "pad.task.search_placeholder" to "インストール済み SKU を検索…",
        "pad.task.offline_note" to "オフライン — この Pad にインストール済みの標準を検索しています。",
        "pad.task.confirm" to "SKU を確定",
        "pad.task.no_standards_installed" to "標準がインストールされていません。管理者に標準バンドルの発行または同期を依頼してください。",
        "pad.task.sku_not_found" to "インストール済み標準に SKU が見つかりません。管理者と同期してください。",

        "pad.work.title" to "検査作業",
        "pad.work.reference" to "標準参照画像",
        "pad.work.log" to "検査ログ",
        "pad.work.input_hint" to "メッセージを入力…",
        "pad.work.send" to "送信",
        "pad.work.voice" to "音声",
        "pad.work.text" to "テキスト",
        "pad.work.capture" to "撮影",

        "readiness.mnn_native_ready_model_pending" to "MNN ネイティブ準備完了；モデル待機中",
        "readiness.model_ready" to "モデル準備完了",
        "readiness.local_runtime_not_ready" to "ローカルランタイム未準備",
        "readiness.no_standard_installed" to "標準未インストール",
        "readiness.no_sku_selected" to "SKU 未選択",
        "readiness.offline" to "オフライン",
        "readiness.online" to "オンライン",

        "pad.review.title" to "結果を確認",
        "pad.review.confirm_pass" to "合格を確定",
        "pad.review.confirm_fail" to "不合格を確定",
        "pad.review.mark_review" to "確認へ回す",
        "pad.review.submit" to "結果を送信",
        "pad.review.submitted" to "結果を同期キューに追加しました。",
        "pad.review.standard_revision" to "標準リビジョン：{rev}",
        "pad.review.bundle_version" to "バンドルバージョン：{ver}",

        "pad.sync.title" to "同期状況",
        "pad.sync.pending" to "{count} 件の結果が未アップロード",
        "pad.sync.none_pending" to "すべての結果をアップロード済み。",
        "pad.sync.upload_now" to "今すぐアップロード",
        "pad.sync.online" to "オンライン",
        "pad.sync.offline" to "オフライン",
    )

    private val tables: Map<String, Map<String, String>> = mapOf(
        "en" to EN,
        "zh-CN" to ZH_CN,
        "ja" to JA,
    )

    /** Build a [GiraffeLanguageSkill] for [locale], English-backed for fail-soft fallback. */
    fun skillFor(locale: String): GiraffeLanguageSkill {
        val normalized = LanguageResolver.normalize(locale) ?: LanguageResolver.DEFAULT_LOCALE
        val table = tables[normalized] ?: EN
        return InMemoryLanguageSkill(locale = normalized, table = table, fallbackTable = EN)
    }
}

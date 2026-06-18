package com.giraffetechnology.qc.qwen

import org.junit.Assert.*
import org.junit.Test

class QcResultParserTest {

    private val ids = listOf("QC-01", "QC-02")

    @Test fun `valid JSON parses correctly`() {
        val raw = """{"overall_result":"pass","engine":"local_qwen_mnn","model_name":"m",
            "confidence":0.9,"summary":"ok","fallback":{"used":false,"reason":null},
            "items":[
              {"qc_point_id":"QC-01","qc_point_code":"c","name":"c","result":"pass","confidence":0.9,"reason":"ok","evidence":{}},
              {"qc_point_id":"QC-02","qc_point_code":"b","name":"b","result":"pass","confidence":0.88,"reason":"ok","evidence":{}}
            ]}""".trimIndent()
        val r = QcResultParser.parse(raw, ids, "local_qwen_mnn")
        assertEquals("pass", r.overallResult)
        assertEquals(2, r.items.size)
        assertEquals("pass", r.items.first { it.qcPointId == "QC-01" }.result)
    }

    @Test fun `markdown-wrapped JSON parses`() {
        val raw = "```json\n" + """{"overall_result":"fail","engine":"local_qwen_mnn","model_name":"m",
            "confidence":0.8,"summary":"","fallback":{"used":false,"reason":null},
            "items":[
              {"qc_point_id":"QC-01","qc_point_code":"c","name":"c","result":"fail","confidence":0.8,"reason":"bad","evidence":{}},
              {"qc_point_id":"QC-02","qc_point_code":"b","name":"b","result":"pass","confidence":0.9,"reason":"ok","evidence":{}}
            ]}""".trimIndent() + "\n```"
        val r = QcResultParser.parse(raw, ids, "local_qwen_mnn")
        assertEquals("fail", r.overallResult)
        assertEquals(2, r.items.size)
    }

    @Test fun `missing QC point becomes review_required`() {
        val raw = """{"overall_result":"pass","engine":"local_qwen_mnn","model_name":"m",
            "confidence":0.9,"summary":"","fallback":{"used":false,"reason":null},
            "items":[
              {"qc_point_id":"QC-01","qc_point_code":"c","name":"c","result":"pass","confidence":0.9,"reason":"ok","evidence":{}}
            ]}""".trimIndent()
        val r = QcResultParser.parse(raw, ids, "local_qwen_mnn")
        val qc02 = r.items.find { it.qcPointId == "QC-02" }
        assertNotNull(qc02)
        assertEquals("review_required", qc02!!.result)
    }

    @Test fun `hallucinated QC point is rejected`() {
        val raw = """{"overall_result":"pass","engine":"local_qwen_mnn","model_name":"m",
            "confidence":0.9,"summary":"","fallback":{"used":false,"reason":null},
            "items":[
              {"qc_point_id":"QC-99","qc_point_code":"FAKE","name":"FAKE","result":"pass","confidence":0.9,"reason":"hallucinated","evidence":{}},
              {"qc_point_id":"QC-01","qc_point_code":"c","name":"c","result":"pass","confidence":0.9,"reason":"ok","evidence":{}}
            ]}""".trimIndent()
        val r = QcResultParser.parse(raw, ids, "local_qwen_mnn")
        assertNull("QC-99 must be rejected", r.items.find { it.qcPointId == "QC-99" })
        assertNotNull("QC-01 must be kept", r.items.find { it.qcPointId == "QC-01" })
        val qc02 = r.items.find { it.qcPointId == "QC-02" }
        assertNotNull(qc02)
        assertEquals("review_required", qc02!!.result)
    }

    @Test fun `invalid JSON fails closed`() {
        val r = QcResultParser.parse("not json at all ???", ids, "local_qwen_mnn")
        assertEquals("review_required", r.overallResult)
        assertEquals("json_parse_failed", r.fallback.reason)
    }

    @Test fun `empty response fails closed`() {
        val r = QcResultParser.parse("", ids, "local_qwen_mnn")
        assertEquals("review_required", r.overallResult)
        assertEquals("empty_response", r.fallback.reason)
    }

    @Test fun `confidence clamped to 0-1`() {
        val raw = """{"overall_result":"pass","engine":"local_qwen_mnn","model_name":"m",
            "confidence":1.5,"summary":"","fallback":{"used":false,"reason":null},
            "items":[
              {"qc_point_id":"QC-01","qc_point_code":"c","name":"c","result":"pass","confidence":-0.3,"reason":"ok","evidence":{}},
              {"qc_point_id":"QC-02","qc_point_code":"b","name":"b","result":"pass","confidence":2.0,"reason":"ok","evidence":{}}
            ]}""".trimIndent()
        val r = QcResultParser.parse(raw, ids, "local_qwen_mnn")
        assertTrue("overall confidence must be ≤1", r.confidence <= 1.0f)
        assertTrue("overall confidence must be ≥0", r.confidence >= 0.0f)
        r.items.forEach { item ->
            assertTrue("${item.qcPointId} confidence ≥0", item.confidence >= 0.0f)
            assertTrue("${item.qcPointId} confidence ≤1", item.confidence <= 1.0f)
        }
    }
}

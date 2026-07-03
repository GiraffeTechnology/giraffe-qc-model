"""Server-rendered configuration UI for the digital inspector.

Training the digital inspector is *configuration*, not model fine-tuning: the
Qwen weights are fixed. "Training" a SKU means configuring its inspection
standard — standard photos, detection points, and pass/fail criteria — which
the VL model consumes as inference context. Human confirmation is the gate that
graduates a standard revision.
"""

# i18n Seam — `giraffe-language-skill` (PRD §11)

S0 contract for how **both** Web and Android bind user-facing text. No screen
hard-codes a string; everything routes through the adapter defined here. English
source strings are the canonical key set in [`en.json`](./en.json).

## Adapter interface

One method resolves a key for the active locale and substitutes `{placeholder}`
tokens. Lookup is **fail-soft**: an unknown key returns the key itself so a
missing translation is visible in QA but never crashes a screen.

### Kotlin (Android)

Defined in [`../kotlin/GiraffeLanguageSkill.kt`](../kotlin/GiraffeLanguageSkill.kt):

```kotlin
interface GiraffeLanguageSkill {
    val locale: String
    fun t(key: String, params: Map<String, String> = emptyMap()): String
    fun has(key: String): Boolean
}
```

### Python (Web) — identical shape

```python
from typing import Protocol, Mapping

class LanguageSkill(Protocol):
    locale: str
    def t(self, key: str, params: Mapping[str, str] | None = None) -> str: ...
    def has(self, key: str) -> bool: ...
```

Both bindings MUST use the same key set, the same `{name}` placeholder syntax,
and the same fail-soft (return-the-key) miss behaviour.

## Key namespaces

`en.json` is flat, dot-namespaced. Every screen named in the S0 scope has keys:

| Namespace | Screen (PRD §11) |
|-----------|------------------|
| `common.*` | Shared controls/errors |
| `state.*` | Standard lifecycle labels (§10) — value matches `StandardState.wire` |
| `verdict.*`, `severity.*`, `view.*` | Shared enums |
| `studio.*`, `detection_point.*` | Admin Studio (message thread, photo upload, confirm/reject/publish, detection-point editor) |
| `bundles.*` | Bundle export, history, download, assign |
| `workstations.*` | Workstation admin |
| `pad.*` | Android Pad (SKU search, install, capture, inspection, result) |

## Rules

1. **Add the key here first.** A new UI string lands in `en.json` before any
   screen references it. Other locale files mirror the same keys.
2. **State/enum labels are derived, not duplicated.** `state.<wire>` keys map
   1:1 to `StandardState` wire values; never invent a second label source.
3. **Placeholders are named** (`{sku}`, `{count}`), never positional.

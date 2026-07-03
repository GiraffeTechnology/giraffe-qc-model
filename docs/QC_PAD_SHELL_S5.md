# S5 — Pad Shell: Welcome / Landscape / i18n / Operator Task Selection

Session 5 builds the Android Pad shell around the existing on-device QC pipeline:
the entry Welcome screen, forced landscape, a language-switch on every screen
bound to the `giraffe-language-skill` seam, and an **offline** Operator Task
Selection driven entirely by the on-device standards store.

## Screens & navigation

```
WelcomeScreen (Giraffe icon · Administrator · Operator · 🌐 language)
  ├─ Administrator → AdministratorInfoScreen (admin runs on the Web console)
  └─ Operator      → OperatorTaskSelectionScreen  (offline installed-standards search)
                        → QcCaptureScreen → ResultScreen   (existing S/M pipeline)
```

`MainActivity` starts at `PadScreen.Welcome`. The legacy backend-LAN
`TaskSelectionScreen` (online SKU search) is retained behind `PadScreen.TaskSelection`.

## Forced landscape (§16.2)

`MainActivity` is declared `android:screenOrientation="landscape"` with
`configChanges="orientation|screenSize|keyboardHidden"` in `AndroidManifest.xml`.
Every operator/QC screen renders inside this single activity, so none can appear
in a broken portrait layout.

## i18n seam (§11)

- `contracts/GiraffeLanguageSkill` — in-app copy of the S0 adapter interface.
- `i18n/LanguageResolver` — pure fallback logic, identical priority to Web:
  **explicit selection > device language > English**. Unit-tested on the JVM.
- `i18n/PadLanguageCatalog` — en / zh-CN / ja tables. English is canonical; any
  gap falls back to English, then to the key itself (fail-soft, never crashes).
- `i18n/LanguageController` — holds the active locale + live `GiraffeLanguageSkill`;
  `ui/LanguageSwitch` is the globe control shown on every screen. No user-facing
  string is hard-coded in a composable.

## Offline Operator Task Selection (§8.1) — hard requirement

- `contracts/SqliteStandardStore` — read surface (in-app copy of the S0 seam).
- `store/AndroidSqliteStandardStore` — SQLite implementation of the read surface
  **and** the `StandardStoreWriter` port. Every lookup is local only — no network.
  Misses return null / empty so callers fail closed.
- `operator/OperatorTaskSelectionController` — the search/confirm state machine:
  - empty store → `NoStandardsInstalled` → exact message
    *"No standards installed. Please ask Administrator to publish or sync a
    standard bundle."*
  - installed but no match → `SkuNotFound` → exact message
    *"SKU not found in installed standards. Please sync with Administrator."*
  - confirm → hydrates the installed active revision (photos + detection points)
    into a `QcTask` carrying `activeStandardRevisionId`, feeding the existing
    `PadInspectionCoordinator` path.

The two spec strings live in the i18n catalog (localized), and a unit test pins
their exact English text so they cannot drift.

## Bundle consumption (§14)

- `store/StandardBundle` — the verified, in-memory bundle shape S5 receives from
  S3 (sync-window pull or USB sideload). Archive signature/checksum verification
  is upstream (offline-sync); anything reaching the importer is trusted content.
- `store/BundleImporter` — fail-closed install: rejects empty bundles, blank ids,
  and **downgrades** (bundle version ≤ installed). The store install is atomic
  (all-or-nothing), so a rejected/failed import leaves prior standards intact.

## Tests (JVM unit)

- `LanguageResolverTest` — fallback priority + tag normalization.
- `PadLanguageSkillTest` — fail-soft, placeholder substitution, and the exact
  S5/S6 spec strings across all three locales.
- `OperatorTaskSelectionControllerTest` — empty-store, offline search, not-found,
  and confirm-builds-QcTask (revision id + photos + points).
- `BundleImporterTest` — populate store, reject empty/blank/downgrade, atomicity.

The SQLite and Compose layers require the Android runtime and are exercised on
device; the pure controller/store/i18n logic is covered by the JVM suite above.

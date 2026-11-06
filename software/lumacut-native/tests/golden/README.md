# Golden-Dateien

`in/` Eingaben, `out/` erzeugt der echte Kotlin-Code aus `android/core` (Stand: `main` mit `op=work_band`).
`ts/extra.json` erzeugt die TypeScript-Fassung für das, was es in Kotlin nicht gibt (Vektorisieren, Kurven).

Neu erzeugen (außerhalb des Repos, `android/` bleibt unverändert):

1. `android/` in einen Scratch-Ordner kopieren, in `settings.gradle.kts` nur `:core`, Android-Plugins entfernen.
2. `tests/golden/tools/GoldenGen.kt` nach `core/src/test/kotlin/de/millione/lumacut/core/` legen.
3. `in/` als `golden-in/` neben `core/` legen, `gradle :core:test --tests '*GoldenGen*'`.
4. `golden-out/*` nach `out/` kopieren.

Gegenprobe (C++ schreibt, Kotlin liest und erzeugt denselben G-Code): `LUMACUT_COMPAT_OUT=<ordner> test_core gegenprobeSchreiben`,
dann `tools/CompatCheck.kt` neben GoldenGen.kt legen und `gradle :core:test --tests '*CompatCheck*'` mit `from-cpp.*` in `compat/`.

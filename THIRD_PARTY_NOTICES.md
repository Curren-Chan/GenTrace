# 依存関係とライセンス

GenTraceのソースはMIT License。著作権表示は個人名を含まない `GenTrace contributors` とした。競合のコード・画像・READMEは取り込んでいない。

今回、すべてのPythonソースのimportと配布候補を調べた。実行時はPython標準ライブラリ、Tcl/Tk、SQLite、Windows OS APIのみ使用し、pipによる追加依存やvendoredコード、フォント、モデル、Python実行環境の同梱はない。スクリーンショットも独自の架空データから作成した。AIによる開発支援の利用は、外部コードのライセンスを取り消す根拠にはならないため、今後コードを移植する場合は出典・条件を確認する。

| 対象 | 条件・扱い | 一次資料 |
|---|---|---|
| CPython / 標準ライブラリ | PSF License等。ユーザーが別途導入する。ソースZIPへ同梱しない | [Python license](https://docs.python.org/3/license.html) |
| Tcl/Tk | BSD型の許諾。Python側の配布条件を維持する必要がある | [Tcl/Tk license](https://www.tcl-lang.org/software/tcltk/license.html) |
| SQLite | public domain。Pythonに含まれるSQLiteを使用 | [SQLite copyright](https://www.sqlite.org/copyright.html) |
| Windows API | OS付属のDLLを呼び出す。DLLを配布しない | [Windows API](https://learn.microsoft.com/en-us/windows/win32/api/) |
| Stability Matrix / ComfyUI | ユーザーの別環境へ設定の読取り・GET APIアクセスを行う。コードをリンク・同梱・改変しない | [Stability Matrix](https://github.com/LykosAI/StabilityMatrix), [ComfyUI](https://github.com/Comfy-Org/ComfyUI) |

候補はMIT、BSD-3-Clause、Apache-2.0。小規模な独立ツールとして再利用しやすく、追加依存も同梱しない現状にはMITが適しているため採用した。Apache-2.0の明示的な特許条項が必要な状況は確認されていない。実行ファイル化してPythonやTcl/Tkを同梱する場合は、各ランタイムのライセンス・第三者表示を改めて収集する。本調査はソースと配布構成の整合確認であり、外部から来歴不明のコードを移植する許可にはならない。

# GenTrace 1.1.0 公開準備結果

2026-10-07。現行ソースへ修正を反映し、個人データとGit履歴を含まない公開用ZIPを用意した。コミット・GitHub公開は行っていない。

## 最優先の監査

全refに到達する6コミット、2つのtag object、22のtree、95のblobを検査した。Git fsckは問題を報告せず、dangling objectも報告しなかった。既知形式の秘密キー、ユーザーホームパス、生成画像/SQLiteのsignatureは履歴に見つからなかった。fixtureは本文のない架空API graphと、テスト用の短い架空本文だけだった。未知形式の秘密や文章中の個人情報まで不存在を証明したものではない。

過去のREADME、AGENTS、configにはローカル絶対パスが残っている。commit/tagの作者名・メールも公開確認が必要。元の履歴は変更せず保持し、公開ZIPに.gitを含めない方針にした。現行ソース内の実ローカルパスは相対設定や架空exampleへ変更した。

作業フォルダの実DB1ファイル、診断ログ1ファイル、CSV等export6ファイルは保全し、移行・diagnose・編集・削除を行っていない。実データを公開ファイルへコピーしていない。フォルダ外のDB/ログ/画像/鍵/環境/モデルにも除外ルールを追加した。元からある開発Skillは保全し、公開ZIPには含めていない。

公開マニフェストで許可したソースと文書のみZIPへ入れる。実設定はconfig.local.json、公開例はconfig.example.json。スクリーンショットは架空記録だけの実UI撮影2枚で、text metadataは0。SHA256 manifestで未レビュー画像を拒否する。元リポジトリにはpre-commit/pre-push guardも追加し、global Git設定や作者情報は変更していない。

## 文書と差別化

READMEに、ローカル画像生成を続ける作者自身の不便から生まれた出自、導入手順、操作、保存情報、非対応を記載。12候補をメタデータ、検索、DB、workflow/prompt、管理、重複、導入、更新で比較し、一次資料とAPI取得snapshotを残した。

SQLite、PNG解析、LoRA/CFG表示、CSV、ジョブ履歴、GPU監視は他のツールにもある。世界唯一の機能は確認できなかった。特徴的なのは、Stability Matrixの設定を読み、ComfyUIへ外部からGETだけで接続し、custom nodeやworkflow変更なしで、本文を永続化せず、ジョブ時間・状態とWindows GPU EngineサンプルをSQLiteに残し、独立Viewerで見る構成。これは比較候補中の設計上の特徴で、世界唯一の証明ではない。

MIT Licenseを採用し、Python/Tcl/Tk/SQLiteとWindows APIの扱いを明文化。追加pip依存、競合ソースや画像、ランタイムやフォントの同梱はない。

## 実装修正

- DB: quick_check、移行前Online Backup、DDLと版情報の一括transaction、rollback、将来版拒否、版情報の不一致拒否。
- PNG: 切断、text CRC、圧縮方式/終端、展開量上限、非有限数、不正pathへの対応。
- Viewer: DB/ファイルエラー案内、定期更新の継続、異常CSV出力の通知。
- CSV: 一時ファイルへ書き、完了時だけ置換。失敗時は既存exportを保全。従来の列順は維持。
- Collector: 個別ファイルの消失/権限エラーで他の候補照合を止めず、再statによる競合を回避。
- 設定: 環境変数とlocal JSON、example、欠損/不正なStability Matrix設定への案内。
- 公開: .gitignore、明示マニフェスト、index/全ref監査、hash確認、ソースZIP、hook、Windows CI設定。

## 検証と実際の確認範囲

ローカルWindows / Python 3.11.9で64テスト合格。schema 1/2/3から4への移行、失敗rollbackとbackup、future schema、破損、DBロック、既存CSV保全、異常PNG、権限エラーと長すぎるpathを確認した。権限不足の一部は例外注入で、OSのACLを変更した実験ではない。構文検査とgit diff --checkも合格。

Windowsの実TkウィンドウへShell形式のdrop通知を送るテストで、取込→SQLite→一覧/詳細→再取込→Present/Missing/Unknownを確認した。安全なdemo2枚は実画面を撮影し目視した。GPUカウンター初期化テストも通ったが、今回の新規生成中のGPU採取を実証したものではない。

公開候補の監査は合格。元のindex/全ref監査は旧パスと作者情報を検出して不合格（想定どおり）。既知キーがないことと、元の履歴をそのまま公開してよいことは同じではない。ソースZIPは展開先で監査とテストを確認する。

## 公開前の残課題

- GitHub公開先を確定し、ZIPから新しい公開用Git履歴を作る。公開用表示名とGitHub noreplyメールをローカル設定し、旧branch/tagを持ち込まない。コミット・公開は未実施。
- 別PCの新規導入、GitHub上のPython 3.11/3.14 CI、新規画像生成を使ったLoggerの実採取は今回未確認。
- 任意custom node、長大workflow、全GPU構成、大量履歴の性能、UNC/network共有、Windowsのすべての長いpathは未保証。
- 本文全文検索、gallery、画像移動・hash重複排除、workflow復元は現行の対象外。
- PNG出力の時刻/設定による照合は曖昧になりうる。GPU使用率はアダプター全体でありComfyUI専用ではない。

詳細な比較表は [competition](competition.md)、チェックリストは [publication](publication.md)、DBは [database](database.md)、対応メタデータは [metadata](metadata.md) を参照。

## 変更・追加ファイル

- `.gitattributes`
- `.github/workflows/checks.yml`
- `.gitignore`
- `AGENTS.md`
- `CHANGELOG.md`
- `LICENSE`
- `README.md`
- `SECURITY.md`
- `THIRD_PARTY_NOTICES.md`
- `VERSION`
- `config.example.json`
- `docs/audit-report.md`
- `docs/competition.md`
- `docs/database.md`
- `docs/development.md`
- `docs/metadata.md`
- `docs/publication.md`
- `docs/research-snapshot.json`
- `docs/screenshots/gpu-demo.png`
- `docs/screenshots/manifest.json`
- `docs/screenshots/viewer-demo.png`
- `gentrace/__init__.py`
- `gentrace/backends/stability_matrix.py`
- `gentrace/collector.py`
- `gentrace/config.py`
- `gentrace/csvexport.py`
- `gentrace/database.py`
- `gentrace/errors.py`
- `gentrace/extract.py`
- `gentrace/gui.py`
- `gentrace/imageimport.py`
- `gentrace/pngmeta.py`
- `main.py`
- `publication-files.txt`
- `scripts/demo.py`
- `scripts/pre-commit`
- `scripts/pre-push`
- `scripts/publication_audit.py`
- `tests/test_filedrop.py`
- `tests/test_publication_audit.py`
- `tests/test_publication_safety.py`

`.git/hooks/pre-commit`と`.git/hooks/pre-push`もローカルに追加した（配布ZIPには含めない）。`.agents/`は既存のまま保全した。`docs/development.md`は既存の未追跡文書にドロップ検証の説明だけを追加した。

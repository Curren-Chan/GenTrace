# 公開前チェックリスト

## 安全な公開元

作業中の個人利用リポジトリをそのままpushする方法は推奨しない。現在のファイルを安全にしても、過去のREADME等の絶対パスやcommit/tagの作者情報はGit履歴に残る。今回、元の履歴は保全し、公開向けには明示したファイル一覧だけの**履歴なしソースZIP**を用意する方式を採用した。

```powershell
python scripts/publication_audit.py
python scripts/publication_audit.py --staged --history
python scripts/publication_audit.py --export ../GenTrace-public-source.zip
```

最初は現在の公開候補とGit管理候補、二番目はさらにindexと全refのblob/commit/tagを検査する。古い履歴や未更新indexがある元のリポジトリでは、二番目が不合格でも現在のソースZIPの監査とは区別する。原本の.gitは配布しない。`publication-files.txt`以外のファイルはZIPへ入れず、既存ZIPを上書きしない。コピー前に同じバイト列を検査する。

公開するときはZIPを新しい空フォルダへ展開し、一覧と画面を確認してから新規Gitリポジトリを作成する。過去の履歴を移さず、公開用の表示名とGitHubのnoreplyメールを**その新しいリポジトリだけ**に設定する。個人用リポジトリの設定やglobal Git設定は変更しない。旧branch/tagを追加pushしない。コミットと公開は今回未実施。

Gitがある環境ではローカルhookも使える。新しい公開用リポジトリで `scripts/pre-commit` を `.git/hooks/pre-commit`、`scripts/pre-push` を `.git/hooks/pre-push` へコピーする。既存hookがある場合は上書きせず、検査処理を組み込む。元の作業リポジトリにも今回この2つのhookを追加し、公開候補/indexの検査と、過去履歴をそのままpushする操作を止める。hookはcloneだけでは自動有効にならず、`--no-verify`でも回避できるため、公開直前の検査を省略しない。

## チェック項目

- [ ] `git status --short` と公開ファイル一覧を確認し、未コミットの他作業を保全する。
- [ ] DB、WAL/SHM、バックアップ、CSV、ログ、画像、モデル、実workflow/本文、キャッシュ、仮想環境、鍵が追跡されていない。
- [ ] `.gitignore`はフォルダ外の機微な拡張子も除外。公開画像は2枚の承認済みデモに限定。
- [ ] `config.example.json`は架空・相対パスのみ。実際の設定は除外された `config.local.json` に置く。
- [ ] 現在の公開候補、index、全ref/commit/tag、作者名・メール・commit message、tag messageを確認する。必要なら `git fsck --full --no-reflogs` でdangling objectの有無も確認する。
- [ ] 秘密情報が見つかったらキーを失効・再発行。削除コミットだけでは履歴から消えない。
- [ ] スクリーンショットに個人名・パス・本物の画像・promptがない。生成PNGのmetadataも見ないで許可しない。
- [ ] 監査の正常終了だけを「安全の保証」と扱わない。未知の秘密形式・文章・binary・画素は目視する。
- [ ] READMEのインストール・出自・用途・非対応・採取限界が現在の実装と一致する。
- [ ] MIT Licenseと依存条件を確認。競合のコード・画像は転用していない。
- [ ] `VERSION`・package・README・CHANGELOGの版番号が一致する。
- [ ] 旧schema 1/2/3、初回作成、将来schema拒否、失敗rollback、backup、破損・ロックを一時DBで検証する。
- [ ] CSV従来列の順序、NULL、同一pathの補完、画像非変更、異常PNGの扱いを検証する。
- [ ] Windows Tkでドロップ → DB → 一覧・詳細・存在状態を確認する。
- [ ] 新規画像生成による実証、別PCの新規導入、GitHub CIは未実施なら明記する。
- [ ] 配布ZIPを展開し、公開監査、テスト、safe demoを実行する。`.git`や実データを含まないことを確認する。
- [ ] GitHubの公開先、noreply identity、private vulnerability reportingの有無を確定してから公開する。

## 監査ツールの範囲

値そのものを出さず、ファイル名・分類・object IDだけを出す。公開マニフェスト、秘密キーの既知prefix、private key header、credential literal、ユーザーホーム/ドライブパス、現在のWindowsユーザー名、SQLite/画像のsignature、危険な拡張子、PNGの承認hashを検査する。`--staged`では実際のindex内容を読む。`--history`では全refに到達可能なblobに加えcommit/tag本文を検査し、作者情報の確認フラグも出す。

現在のソースと旧履歴は別の検査結果を持つ。履歴を書き換える機能はない。GitがないソースZIPの展開先ではマニフェストとその内容を検査する。マニフェスト外の未追跡ファイル検査はGitリポジトリで行う。PNG hash manifestは目視レビュー後の版に固定し、再撮影したら再確認する。CIはテストとindex監査を行うが、公開後にしか走らないので漏えいの事前防止をhook/手動検査で補う。

## デモの再撮影

`python scripts/demo.py --capture docs/screenshots` はWindowsでデモのウィンドウだけを取得する。デスクトップ全体を撮影しない。記録、時刻、モデル名、GPU値、存在しない `C:/demo/` パスはすべて架空で、API・Logger・実画像・実DBは使用しない。生成画像は説明用の実UIキャプチャであり、実生成の証拠ではない。

再撮影後は2枚を目視し、PNG text chunkがないことを確認してから `docs/screenshots/manifest.json` のSHA256を更新する。通常利用者が起動するデモは一時DBを自動削除する。公開ZIPにDBや生成PNGを同梱する必要はない。

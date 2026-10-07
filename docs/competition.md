# 競合調査とGenTraceの位置づけ

調査日: 2026-10-07。GitHubを中心に英語・中国語のREADME、公式リリース、DB/検索の説明、GitHub APIで取得したdefault branchの最新commitとreleaseを調べた。実機へのインストール・速度測定は行っていない。各機能は作者の文書やソースに基づき、記載のない機能を「存在しない」とは断定しない。

探索語: `ComfyUI image browser SQLite metadata search`, `ComfyUI gallery history prompt manager`, `PNG metadata viewer`, `prompt archive`, `ComfyUI history database job logger GPU utilization`。画像閲覧・検索だけに偏らないよう、ジョブ履歴とGPU監視も追加した。世界中の全ツールを網羅した調査ではなく、主要な設計群から12候補を比較する。星の数や名称だけで採用・除外しない。

## 目的・メタデータ・検索・DB

| 候補 / 一次資料 | 主な目的 | 対応メタデータ | 検索性 | DB利用 |
|---|---|---|---|---|
| [Diffusion Toolkit](https://github.com/RupertAvery/DiffusionToolkit) | Windowsの画像index・整理 | A1111等の設定、ComfyUI node/raw/workflow | prompt・Seed・CFG等の構文検索、workflow検索 | SQLite。raw/workflow保存は設定式 |
| [Infinite Image Browsing](https://github.com/zanllp/infinite-image-browsing) | 多形式画像・動画管理 | A1111、ComfyUI（READMEは部分対応）、Fooocus、NovelAI等 | prompt/model/LoRAタグ、複合・曖昧検索 | SQLiteのindex。DB利用はソースのdb層でも確認 |
| [SD Prompt Reader](https://github.com/receyuki/stable-diffusion-prompt-reader) | 単画像の設定・本文閲覧 | 多生成形式、PNG/JPEG/WebP。ComfyUIは制限あり | 単画像閲覧・本文コピー中心。永続ライブラリ検索は明記なし | 永続archive DBの説明なし |
| [Sidebar Gallery](https://github.com/TokenSpender/ComfyUI-Sidebar-Gallery) | ComfyUI内のmedia gallery | ComfyUI、A1111系、Fooocus等。prompt、model、LoRA等 | 全項目、field prefix、AND/OR | SQLite |
| [PromptManager](https://github.com/ComfyAssets/ComfyUI_PromptManager) | prompt再利用・分類・gallery | 正負本文、workflow、設定、LoRA | tag・rating・本文・metadata検索 | SQLite |
| [ComfyUI-Gallery](https://github.com/PanicTitan/ComfyUI-Gallery) | リアルタイム出力閲覧 | PNG/JPEG metadata、workflow設定、raw JSON | filename検索・sortが明記。DB全文検索は不明 | READMEではarchive DBを確認できず |
| [Image Metadata Viewer](https://github.com/sipvaclav-design/image-metadata-viewer) | ブラウザ内のfolder解析 | ComfyUI、A1111、EXIF/XMP/IPTC等 | folder内の任意値、LoRA/Seed等 | backend DBなし。永続SQLite archiveではない |
| [ComfyUI-RunHistory](https://github.com/livobing/ComfyUI-RunHistory/blob/main/ComfyUI-RunHistory/README.md) | 再起動後も残る実行履歴 | 状態・時間・完全workflow/API prompt・出力 | 状態filter。本文全文検索は不明 | SQLite + WAL、圧縮workflow |
| [ComfyUI-AMDMonitor](https://github.com/the-Macro-Man/ComfyUI-AMDMonitor) | GPU/VRAM・実行時診断 | model/LoRA/寸法/CFG等、node時間、error | 履歴パネル・CSV。検索archiveは不明 | 実行履歴のdisk保存。SQLiteとは未確認 |
| [ai-gallery](https://github.com/quzopl/ai-gallery) | ローカルの複数library管理 | ComfyUI/A1111、prompt・設定、raw metadata | SQLite FTS5、model/LoRA/tag/favorite | SQLite + FTS5 |
| [Breadboard](https://github.com/cocktailpeanut/breadboard) | 複数生成appの画像browser | A1111、InvokeAI、DiffusionBeeが明記 | prompt検索 | READMEのDB方式は不明 |
| [ComfyUI Image Browser / Hanaikada](https://github.com/licyk/comfyui-image-browser) | ComfyUI内の画像整理・比較 | workflowからprompt/Seed/model/Sampler | 検索・tag・比較 | extension READMEだけではDB方式を確定せず |
| GenTrace 1.1.0 | 外部のジョブ履歴ロガー | 抽出した生成設定・時間・GPU。本文保存なし | 日付・状態・モデル部分一致。1000件上限 | SQLite。画像本体なし |

補足一次資料: Diffusion Toolkitの [v1.8以降のworkflow検索説明](https://github.com/RupertAvery/DiffusionToolkit/releases) と [検索構文](https://github.com/RupertAvery/DiffusionToolkit/blob/master/Diffusion.Toolkit/Tips.md)。IIBの [DBソース](https://github.com/zanllp/infinite-image-browsing/blob/main/scripts/iib/db/datamodel.py)。ComfyUI parserの複雑なgraphへの制限は各READMEの条件を優先する。

## workflow / prompt、画像管理、重複、導入

| 候補 | ComfyUI workflow / prompt | 画像管理 | 重複排除 | 導入 |
|---|---|---|---|---|
| Diffusion Toolkit | workflow/raw閲覧・検索 | gallery、album、rating、移動 | path tracking。content hash重複除去の保証は未確認 | Windows release / .NET構成 |
| IIB | 部分対応、metadata/raw閲覧 | gallery、favorite、ファイル操作 | content単位の排除仕様は未確認 | desktop、Python standalone、SD-webui extension |
| SD Prompt Reader | basic workflow解析。複雑なcustom nodeは制限 | 閲覧、prompt編集・除去・export | library重複排除は説明なし | release、pip、GUI/CLI |
| Sidebar Gallery | raw/API/UI workflow、canvasへ再読込 | 画像・動画・音声grid | 増分index。content hash排除は未確認 | ComfyUI custom_nodes / Manager |
| PromptManager | 本文の永続保存、workflow分析 | gallery、tag、rating、thumbnail | SHA256で**同一prompt**の保存重複を防止。画像重複とは区別 | CLIPTextEncode等に代わるcustom node |
| ComfyUI-Gallery | metadata閲覧・copy、raw JSON | realtime、ZIP download、media preview | content排除は未確認 | custom_nodes、依存導入 |
| Metadata Viewer | 上流追跡、workflow copy、raw dump | folder gallery、JSON/CSV export | content排除は未確認 | 静的HTML、offline / hosted |
| RunHistory | 完全snapshot保存・canvas復元 | 出力media参照・preview、履歴削除 | prompt_idの一意性。画像hash排除とは別 | custom_nodes、実行関数/eventへhook、標準ライブラリ |
| AMDMonitor | 実行設定・error・per-node診断 | run history、CSV、live preview | 画像hash排除は未確認 | ComfyUI extension。disk履歴は既定50件 |
| ai-gallery | workflow/prompt抽出、rich-metadata nodeも併用可能 | gallery・複数library・tag・favorite・移動 | schemaにsha1あり。ただしhash列だけで画像削除を保証しない | Python/uv、FastAPI、Pillow、watchdog |
| Breadboard | ComfyUI対応はREADMEで確認できず | bulk delete、他appへのdrag | content排除は未確認 | Electron / npm / release |
| Hanaikada extension | workflowを新tabへ復元、Load Imageへ送信 | 画像比較・tag・移動・rename・削除 | extension READMEでは未確認 | custom_nodes、Hanaikada依存。Node build不要 |
| GenTrace | API promptから設定だけ抽出。workflow復元と本文検索なし | 外部画像参照。gallery/移動/削除なし | 同じ絶対パスとjob ID。content hashなし | Windows、Python/Tk、追加pip/custom node不要 |

## 更新状況

APIから2026-10-07に取得したdefault branchの最新commit日時（UTC）と最新release。取得したSHA・ライセンス識別・archived状態は [調査snapshot](research-snapshot.json) に記録。release未登録は更新停止を意味しない。default branchよりreleaseの日時が新しい場合も、そのまま区別している。すべて取得時点でarchived=false。

| 候補 | 最新commit (UTC) | 最新release / 公開日 (UTC) |
|---|---|---|
| [DiffusionToolkit](https://github.com/RupertAvery/DiffusionToolkit/commit/153409c3a0e9569886e6601530365808d4ecbb0e) | 2026-02-27 | v1.10 / 2026-01-06 |
| [infinite-image-browsing](https://github.com/zanllp/infinite-image-browsing/commit/7530eaf5c7e10465caf83f07e312a14f195f17dd) | 2026-10-03 | v1.9.0 / 2026-08-22 |
| [stable-diffusion-prompt-reader](https://github.com/receyuki/stable-diffusion-prompt-reader/commit/32b2eea715b5f7816222cef23af3deed7df04a30) | 2024-05-29 | v1.3.5 / 2024-05-21 |
| [ComfyUI-Sidebar-Gallery](https://github.com/TokenSpender/ComfyUI-Sidebar-Gallery/commit/07e1d0e8b69f939ff52b964f812818b5ee6b7c96) | 2026-09-04 | v1.1.4 / 2026-09-04 |
| [ComfyUI_PromptManager](https://github.com/ComfyAssets/ComfyUI_PromptManager/commit/d70dab56e5fb67c3e471607bc10984975c4cc2aa) | 2026-06-29 | 登録なし / - |
| [ComfyUI-Gallery](https://github.com/PanicTitan/ComfyUI-Gallery/commit/74639e68846f64c9f561f3a7745529de76376a97) | 2026-06-22 | 登録なし / - |
| [image-metadata-viewer](https://github.com/sipvaclav-design/image-metadata-viewer/commit/b6dba2789302f8584372064edaad65e05fc3b5ea) | 2026-08-10 | 登録なし / - |
| [ComfyUI-RunHistory](https://github.com/livobing/ComfyUI-RunHistory/commit/831b52e307f24600a6479d6b3b2ed730c41419ae) | 2026-08-23 | v1.4 / 2026-09-27 |
| [ComfyUI-AMDMonitor](https://github.com/the-Macro-Man/ComfyUI-AMDMonitor/commit/64315d8122892efc7b2e2f9a29c60eb5d8b3d2c5) | 2026-10-02 | 登録なし / - |
| [ai-gallery](https://github.com/quzopl/ai-gallery/commit/cf02aa3af0e00b01e462c3687ae0ec7c2d0d633f) | 2026-08-18 | 登録なし / - |
| [breadboard](https://github.com/cocktailpeanut/breadboard/commit/fcbef0910918a7c7b2cdb470eca63931289eafc7) | 2023-03-08 | 0.4.5 / 2023-03-08 |
| [comfyui-image-browser](https://github.com/licyk/comfyui-image-browser/commit/17db3aec56cc4119392854224b67bbc0cddb6b7f) | 2026-10-02 | 登録なし / - |


## GenTraceにしかない価値をどう扱うか

世界唯一と証明できる機能は確認できなかった。RunHistoryには永続ジョブ履歴・時間・状態・画像参照があり、AMDMonitorにはGPU/実行設定の監視・CSVがある。Metadata Viewerには追加backendなしのローカル解析、複数ツールにはSQLiteとLoRA解析がある。この事実に合わせてREADMEの売り文句を修正した。

**比較候補中でGenTraceの特徴的な組合せ**は、Stability Matrixの設定を読み、ComfyUIへGETで外部から接続し、custom nodeやworkflow変更なしで、本文を永続化せず、ジョブの時間・状態とWindows PDHサンプルをSQLiteに残し、独立したViewerから見ること。これは設計上の適合性であり、競合に同じ構成がないという証明ではない。GPU値もプロセス専用ではないため「ComfyUIのGPU利用率を正確に測る」という主張は避ける。

既存ツールと被る価値: ローカル利用、PNG設定抽出、SQLite永続化、LoRA/CFG/Seed表示、CSV、既存画像への参照、失敗・中断履歴。これらを独自性の根拠にはしない。

READMEで主張しない点: 最強・最速・世界唯一、完全なprompt/workflow管理、万能検索、content hash重複排除、画像の安全な整理機能、全custom node対応、個人情報の完全非保存、完璧な出力紐付け、旧ComfyUI全面互換、大量データ性能、GPU専用負荷の精密計測。

画像検索・ギャラリーにはDiffusion Toolkit/IIB/Sidebar Gallery/ai-gallery、本文再利用にはPromptManager、単画像解析にはSD Prompt Reader/Metadata Viewer、workflow復元込みのジョブ履歴にはRunHistory、詳細GPU診断にはAMDMonitorが比較対象になる。GenTraceは競合を置き換える万能管理ツールとして宣伝せず、作者自身の生成履歴確認の不便を解決する構成として説明する。

# 対応メタデータと保存範囲

| 入力 | 保存する項目 | 条件・制限 |
|---|---|---|
| Stability Matrix PNG `parameters-json` | `ModelName`, `LoraNames`等、`Width`, `Height`, `Sampler`, `Scheduler`, `Steps`, `CfgScale`, `Seed` | JSON objectのみ。LoRAはキーの表記違いを許容。本文は保存しない |
| ComfyUI PNG `prompt` | モデル・LoRA名称・寸法・Sampler・Scheduler・Steps・CFG・Seed | API execution graphを解析。モデルと寸法はSamplerの上流をたどる。通常のLoraLoader、rgthree Power Lora Loader等。任意のcustom nodeを完全解釈する保証はない |
| A1111形式PNG `parameters` | `Model`, `Size`, `Sampler`, `Schedule type`, `Steps`, `CFG scale`, `Seed` | `Steps:`で始まる設定行だけを解析。LoRA、本文、negative promptは保存しない。全A1111派生形式の互換保証ではない |
| ComfyUI実行中API | 上記の生成設定、開始・終了・生成時間、状態、ジョブID | `/api/jobs`, `/api/jobs/{id}`, `/queue`。古いComfyUIの `/history` へのfallbackはない |
| Windows GPU Engine PDH | 生成中の約1秒間隔の使用率、平均・最大・サンプル数 | 指定physical indexの最も忙しいengine。ComfyUIプロセス専用値ではなく、他プロセスも含むアダプターの値。VRAM・温度・消費電力は採取しない |
| 出力ファイル照合 | 絶対パス、枚数、ファイル名、存在状態 | PNGの時刻・設定による照合は複数の同一設定ジョブで曖昧になりうる。画像は外部に残り、移動追跡はしない |

PNGテキストは `tEXt`・`zTXt`・`iTXt` に対応。手動取込時の優先順は `parameters-json` → `prompt` → `parameters`。正常な情報があれば壊れた任意JSONを無視して利用できる項目を保存する。未取得項目はNULL、LoRA未使用と認識できた場合は空文字。整数はSQLiteのsigned 64 bit、CFGは有限数のみ。

PNGのテキスト・IENDの長さとCRC、圧縮データの終端を検査する。単一テキストと展開量は2 MiB、合計予算は8 MiB。非テキストの画素データは展開しないため、画素破損の全面検査ではない。大きなworkflowを含むPNGは上限でスキップされうる。

対応しないもの: `workflow`しかないPNGのUI graph復元、JPEG/WebP/動画のメタデータ、EXIF/XMP、プロンプト全文検索、モデルhash解決、LoRA強度の保存、content hashでの画像重複排除。未知形式は無理に推測せず、理由を表示してスキップする。

同じ正規化絶対パスの取込は一件に集約し、既存の未記録項目だけを補完する。同じ画像でも別パスなら別件。日付・状態・モデル名で絞り込めるが、LoRA/CFG/Seedなどの値による直接検索は現在ない。一覧は最大1000ジョブ。手動取込の生成日時・生成秒数・GPUは不明のままで、日付絞り込みには入らない。

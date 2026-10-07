# DBの初回作成・移行・復旧

永続保存先は `data/gentrace.db`。スキーマ版は `PRAGMA user_version` と `app_state.schema_version` に記録し、現在は4。アプリの版1.1.0とは独立する。

| 版 | 追加内容 |
|---|---|
| 1 | jobs / outputs / gpu_samples / app_stateと基本生成設定 |
| 2 | jobs / outputsのnullableなLoRA名称 |
| 3 | jobsのnullableなBackend |
| 4 | jobs / outputsのnullableなCFG |

初回はディレクトリ・テーブル・indexを作成する。既存GenTrace DBはquick_checkを行い、旧版ならPythonの [SQLite Online Backup API](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup) で `data/backups/` に移行前の独立した `.bak` を保存する。このバックアップはWAL内の確定データも含む。バックアップを作れなければ移行を進めない。

DDL、不足列の追加、両方の版情報を `BEGIN IMMEDIATE` の一つのトランザクションで確定する。`executescript`の暗黙COMMITを使わない。失敗時はrollbackし、元の履歴・版・移行前バックアップを残して起動エラーを表示する。成功済みの起動でバックアップを無制限に増やさず、再実行してもジョブは増えない。WAL設定や新規空ファイルの作成など、トランザクション外のファイル状態まではrollbackの対象ではない。

将来の版のDBは拒否し、版番号を引き下げない。無関係なSQLite構成・破損DBを検出したら拒否し、自動削除・再作成・VACUUM・履歴の推測補完はしない。user_version 0の従来構成はテーブルを確認して扱う。移行バックアップには個人情報を含むため公開しない。

DBロック時はbusy_timeoutで最大5秒待ち、解消しなければエラーを表示する。Viewerは次の定期更新を続け、Loggerは収集ループでエラーを記録して再試行する。ただしロック・停止の間にComfyUI側の履歴が消えたジョブまで回収できる保証はない。CSVは同じ保存先フォルダの一時ファイルへ書き、完了時だけ置換する。DB読取りや保存に失敗した場合は既存CSVを保持する。

復旧はLoggerとViewer、外部DB編集ツールをすべて終了し、現在のDB・`-wal`・`-shm`を別の非公開フォルダへ保全してから行う。使用する `.bak` のコピーを `data/gentrace.db` として配置し、旧DBのWAL/SHMを同じ場所に残さない。元の保全ファイルは削除しない。現行版を再起動すると旧バックアップは再移行される。移行後のDBを旧アプリへ戻すdowngradeはサポートしない。

稼働中にDB本体だけコピーしてもWALの未checkpointデータを落とす可能性があるため、通常バックアップにもOnline Backup APIを使う。参考: [SQLite backup](https://www.sqlite.org/backup.html)。CSV列は従来順を維持し、CFGはBackendの後ろに追加する。

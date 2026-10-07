# GenTrace

- このルートはStability Matrix用のポータブル版。別プロジェクトのGenTraceの設計を混ぜない。
- SQLiteが継続保存先、CSVが必要時の出力。既存DB・CSV列の互換性を維持する。
- Loggerは収集と保存、Viewerは保存済みログの閲覧を担当する。
- 画像は絶対パス参照のみ。画像管理やStability Matrix／ComfyUI側の変更を追加しない。
- 構成・起動・保存場所は [README.md](README.md) の該当節を参照する。
- 検証を依頼された場合や機能変更の検証では、リポジトリSkill `gentrace-verify` を使う。文章修正だけなら適用しない。
- DB／CSV変更・UI検証・リリース時の条件は [docs/development.md](docs/development.md) の該当節を読む。
- 改修ごとにREADMEの「バージョン規則」に従い、確認を求めず`x.y.z`を自動更新する。メジャーは`x`、マイナーは`y`、小規模改修・バグ修正は`z`。一連の改修につき1回更新し、`VERSION`・`__version__`・README・CHANGELOGを揃える。コミット・公開は依頼された場合に行う。

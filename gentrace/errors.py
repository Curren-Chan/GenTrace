"""データを保全するためのエラー案内。"""

import sqlite3


def error_message(exc: Exception) -> str:
    """元の診断に、DBの削除を伴わない対処方法を付ける。"""
    if isinstance(exc, sqlite3.Error):
        code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
        if code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
            return "DBが使用中です。別のDB編集ツールを閉じ、少し待って再試行してください。"
        if code in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}:
            return "DBが破損しているかSQLite形式ではありません。GenTraceを終了し、DBとWALを保全してバックアップから復元してください。自動削除はしません。"
        return f"DBを読み書きできません。保存先の権限と空き容量を確認してください。\n{exc}"
    if isinstance(exc, PermissionError):
        return "ファイルへのアクセス権限がありません。読み取り権限と保存先の書き込み権限を確認してください。"
    if isinstance(exc, OSError):
        return f"ファイル操作に失敗しました。存在・権限・パスの長さ・空き容量を確認してください。\n{exc}"
    return str(exc)

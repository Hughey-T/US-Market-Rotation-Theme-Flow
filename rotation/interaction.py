"""Minimal deterministic command state for Custom GPT smoke tests."""
from __future__ import annotations

from .presentation import render_phase


class ConversationSession:
    def __init__(self, snapshot: dict):
        self.snapshot = snapshot
        self.phase = 0

    def handle(self, command: str) -> str:
        if command == "更新":
            self.phase = 1
            return render_phase(self.snapshot["user_view"], self.phase)
        if command == "次":
            if self.phase == 0:
                self.phase = 1
            else:
                self.phase = min(6, self.phase + 1)
            return render_phase(self.snapshot["user_view"], self.phase)
        if command == "詳細":
            return f"技術詳細（段階{self.phase or 1}）は監査用JSONの対応セクションを参照してください。"
        if command == "用語":
            return "市場平均と比べた強さは、同じ期間のS&P500との差です。広がりは、構成銘柄の何社まで上昇が及んでいるかを示します。"
        if command == "再評価":
            self.phase = 1
            return render_phase(self.snapshot["user_view"], self.phase)
        raise ValueError("supported commands: 更新, 次, 詳細, 用語, 再評価")

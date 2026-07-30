"""Minimal deterministic command state for Custom GPT smoke tests."""
from __future__ import annotations

from .presentation import render_phase


class ConversationSession:
    def __init__(self, snapshot: dict):
        self.snapshot = snapshot
        self.phase = 0

    def handle(self, command: str) -> str:
        command = command.strip()
        if command == "更新":
            if self.phase:
                return "このセッションでは既に分析が開始されています。最新データで最初から開始する場合は、新しいセッションで「更新」と送信してください。"
            self.phase = 1
            return render_phase(self.snapshot["user_view"], self.phase)
        if command == "次":
            if self.phase == 0:
                self.phase = 1
            else:
                self.phase = min(6, self.phase + 1)
            return render_phase(self.snapshot["user_view"], self.phase)
        raise ValueError("supported commands: 更新, 次")

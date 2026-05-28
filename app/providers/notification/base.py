"""通知プロバイダ抽象。LINE 以外への拡張余地を残すために挟む。"""

from __future__ import annotations

from abc import ABC, abstractmethod


class Notifier(ABC):
    @abstractmethod
    def send_text(self, message: str) -> None:
        """プレーンテキストを 1 通として送る (改行込み)。"""

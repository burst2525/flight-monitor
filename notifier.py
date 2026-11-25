import requests
from typing import Optional


class NtfyNotifier:
    """ntfy.sh を利用したiPhoneへのプッシュ通知クラス"""

    def __init__(self, topic: str, server: str = "https://ntfy.sh", default_priority: str = "high"):
        self.topic = topic
        self.server = server.rstrip("/")
        self.default_priority = default_priority
        self.url = f"{self.server}/{self.topic}"

    def send(
        self,
        title: str,
        message: str,
        click_url: Optional[str] = None,
        priority: Optional[str] = None,
        tags: Optional[list] = None,
    ) -> bool:
        """
        iPhoneにプッシュ通知を送信します。
        
        :param title: 通知タイトル
        :param message: 通知本文
        :param click_url: タップ時に開くURL (例: Google Flights予約リンク)
        :param priority: 優先度 (min, low, default, high, urgent)
        :param tags: アイコン・絵文字タグ (例: ['airplane', 'moneybag'])
        """
        priority = priority or self.default_priority
        headers = {
            "Title": title.encode("utf-8").decode("latin-1"),
            "Priority": priority,
        }

        if click_url:
            headers["Click"] = click_url

        if tags:
            headers["Tags"] = ",".join(tags)

        try:
            response = requests.post(
                self.url,
                data=message.encode("utf-8"),
                headers=headers,
                timeout=10,
            )
            response.raise_for_status()
            print(f"✅ iPhoneへ通知を送信しました: {title}")
            return True
        except Exception as e:
            print(f"❌ 通知送信に失敗しました: {e}")
            return False

    def test_notification(self) -> bool:
        """テスト通知をiPhoneへ送信"""
        return self.send(
            title="✈️ 航空券通知システム: 接続テスト",
            message="iPhoneへのプッシュ通知連携が正常に完了しました！\n格安航空券が見つかるとここに即座に速報が届きます。",
            click_url="https://www.google.com/travel/flights",
            priority="high",
            tags=["airplane", "tada"],
        )

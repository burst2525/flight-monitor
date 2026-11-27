import json
import os
import statistics
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple, List

# 大阪(KIX/ITM)発の一般的な通常相場（目安：往復総額 JPY）
# ※データが蓄積されると、自動的に実際の観測中央値に学習・更新されます
DEFAULT_TYPICAL_PRICES = {
    # 国内
    "OKA": 25000,   # 沖縄(那覇) 通常: 約2.5万円 (セール時: 1万円台前半)
    "ISG": 32000,   # 沖縄(石垣島) 通常: 約3.2万円 (セール時: 1.5〜1.8万円)
    "SHI": 28000,   # 沖縄(下地島/宮古) 通常: 約2.8万円 (セール時: 1.5万円以下)
    "CTS": 24000,   # 札幌(新千歳) 通常: 約2.4万円 (セール時: 1.2万円以下)
    "HND": 20000,   # 東京(羽田) 通常: 約2.0万円
    "FUK": 16000,   # 福岡 通常: 約1.6万円
    # 東アジア (台湾・韓国など)
    "TPE": 42000,   # 台北(桃園) 通常: 約4.2万円 (エアアジア等のセール時: 1万円台！)
    "KHH": 40000,   # 高雄(台湾) 通常: 約4.0万円 (セール時: 1万円台)
    "ICN": 32000,   # ソウル(仁川) 通常: 約3.2万円 (セール時: 1.5万円以下)
    "PUS": 24000,   # 釜山(韓国) 通常: 約2.4万円 (セール時: 1万円台前半)
    "HKG": 48000,   # 香港 通常: 約4.8万円 (セール時: 2万円台前半)
    # 東南アジア
    "BKK": 62000,   # バンコク 通常: 約6.2万円 (エアアジアセール時: 2.5〜3万円台)
    "DMK": 58000,   # バンコク(ドンムアン) 通常: 約5.8万円
    "DAD": 52000,   # ダナン 通常: 約5.2万円 (ベトジェット等セール時: 2万円台)
    "HAN": 50000,   # ハノイ 通常: 約5.0万円
    "SGN": 52000,   # ホーチミン 通常: 約5.2万円
    "CEB": 48000,   # セブ島 通常: 約4.8万円 (セール時: 2万円台)
    "MNL": 42000,   # マニラ 通常: 約4.2万円 (セブパシフィックセール時: 1.8万円〜)
    "KUL": 58000,   # クアラルンプール 通常: 約5.8万円 (エアアジア本拠地: 2.8万円〜)
    "SIN": 58000,   # シンガポール 通常: 約5.8万円
    "KUL_SIN": 58000, # マレーシア➔シンガポール周遊 通常: 約5.8万円
    "SIN_KUL": 58000, # シンガポール➔マレーシア周遊 通常: 約5.8万円
    "DPS": 68000,   # バリ島 通常: 約6.8万円
    # ヨーロッパ・周辺 (物価安国)
    "IST": 140000,  # イスタンブール 通常: 約14.0万円 (セール時: 7〜8万円台)
    "BUD": 150000,  # ブダペスト 通常: 約15.0万円
    "WAW": 150000,  # ワルシャワ 通常: 約15.0万円
    "PRG": 160000,  # プラハ 通常: 約16.0万円
    "CAI": 130000,  # カイロ 通常: 約13.0万円
    "TBS": 135000,  # ジョージア(トビリシ) 通常: 約13.5万円
}

# 主要航空会社コードのマッピング（通知に会社名を表示）
AIRLINE_NAMES = {
    "D7": "エアアジアX",
    "XJ": "タイ・エアアジアX",
    "FD": "タイ・エアアジア",
    "AK": "エアアジア",
    "Z2": "フィリピン・エアアジア",
    "MM": "Peach(ピーチ)",
    "IT": "タイガーエア台湾",
    "VJ": "ベトジェット",
    "TR": "スクート",
    "7C": "チェジュ航空",
    "TW": "ティーウェイ航空",
    "LJ": "ジンエアー",
    "5J": "セブパシフィック",
    "TK": "ターキッシュエアラインズ",
    "JL": "JAL",
    "NH": "ANA",
    "CI": "チャイナエアライン",
    "BR": "エバー航空",
    "CX": "キャセイパシフィック",
}


class PriceHistoryManager:
    """通常価格（相場）の自動算出と、相場急落・メガセール（例: 台湾1万円台）を検知するクラス"""

    def __init__(self, history_file: str = "price_history.json"):
        self.history_file = history_file
        self.history = self._load()

    def _load(self) -> Dict[str, Any]:
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save(self):
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 履歴ファイルの保存に失敗: {e}")

    def get_typical_price(self, destination: str, route_key: Optional[str] = None) -> float:
        """路線の通常相場を算出（一時的なセール価格に引きずられないよう安全ガード付き）"""
        default_price = float(DEFAULT_TYPICAL_PRICES.get(destination, 50000))

        all_samples = []
        if route_key and route_key in self.history:
            all_samples.extend(self.history[route_key].get("price_samples", []))
        elif not route_key:
            for r_key, data in self.history.items():
                if destination in r_key:
                    all_samples.extend(data.get("price_samples", []))

        # 最低10サンプル以上あり、かつ極端なセール価格に引きずられていない妥当な範囲(相場の75%〜200%)であれば採用
        if len(all_samples) >= 10:
            observed = float(statistics.median(all_samples))
            if default_price * 0.75 <= observed <= default_price * 2.0:
                return observed

        return default_price

    def evaluate_deal(
        self,
        destination: str,
        route_key: str,
        current_price: float,
        discount_threshold_percent: float = 25.0,
        cooldown_hours: int = 12,
        budget_limit: Optional[int] = None,
    ) -> Tuple[bool, dict]:
        """
        通常相場からの大幅値下がり、またはユーザー指定の予算上限クリアを判定します。
        """
        typical_price = self.get_typical_price(destination, route_key)
        drop_amount = typical_price - current_price
        discount_rate = (drop_amount / typical_price) * 100 if typical_price > 0 else 0

        record = self.history.get(route_key, {})
        now = datetime.now()
        last_price = record.get("last_price", float("inf"))
        min_price = record.get("min_price", float("inf"))
        last_notified_str = record.get("last_notified_at")

        is_budget_deal = budget_limit is not None and current_price <= budget_limit

        analysis = {
            "current_price": int(current_price),
            "typical_price": int(typical_price),
            "drop_amount": int(drop_amount),
            "discount_rate": round(discount_rate, 1),
            "is_mega_deal": False,
            "is_budget_deal": is_budget_deal,
            "budget_limit": budget_limit,
            "status": "normal",
            "reason": "",
            "priority": "high",
        }

        # 通常相場からの下落率が基準未満 かつ 予算上限以下でもない場合は通知対象外
        if discount_rate < discount_threshold_percent and not is_budget_deal:
            return False, analysis

        analysis["status"] = "cheap"

        # 【超破格メガセール検知】40%以上の値下がり または 予算上限クリア
        if discount_rate >= 40:
            analysis["is_mega_deal"] = True
            analysis["priority"] = "urgent"  # 最優先通知（iPhoneのマナーモード貫通）
            budget_txt = f"＆設定予算クリア({budget_limit:,}円以下)" if is_budget_deal else ""
            analysis["reason"] = f"🚨【超破格メガセール！】通常相場より約{round(discount_rate)}% OFF（-{int(drop_amount):,}円安）{budget_txt}"
        elif is_budget_deal:
            analysis["priority"] = "urgent"
            analysis["reason"] = f"🎯【予算上限クリア！】設定予算（{budget_limit:,}円以下）を達成！通常より{round(discount_rate)}% OFF（-{int(drop_amount):,}円安）"
        elif current_price < min_price and min_price != float("inf"):
            analysis["reason"] = f"🔥 過去最安値を更新！(-{int(min_price - current_price):,}円安)"
        elif last_price != float("inf") and (last_price - current_price) >= 1500:
            analysis["reason"] = f"📉 前回よりさらに値下がり！(-{int(last_price - current_price):,}円安)"
        else:
            analysis["reason"] = f"🎉 通常より【{round(discount_rate)}% OFF】の大幅安（-{int(drop_amount):,}円安）"

        # 【賢い通知制御：通知ラッシュ防止 ＆ 売り切れ後の再出現（復活・新枠）を検知】
        if last_notified_str:
            last_notified = datetime.fromisoformat(last_notified_str)
            last_notified_price = record.get("last_notified_price", float("inf"))

            # 1. 前回の通知価格よりさらに1,000円以上安くなった場合（最安値更新）➔ 即通知！
            if current_price < last_notified_price - 1000:
                analysis["reason"] = f"🔥 前回の通知よりさらに値下がり！最安値を更新 (-{int(last_notified_price - current_price):,}円)"
                return True, analysis

            # 2. 一度売り切れて値上がり（通常相場に戻る、または急騰）した後に、再び格安枠が出現した場合 ➔ 即通知！
            # 例: 10,000円が売れて35,000円になった後、新たに11,000円が出現したケース
            is_sold_out_revival = (
                record.get("sold_out_detected", False)
                or (last_price != float("inf") and (last_price >= typical_price * 0.70 or last_price >= last_notified_price + 5000))
            )
            if is_sold_out_revival:
                budget_txt = f" (設定予算 {budget_limit:,}円以下クリア)" if is_budget_deal else ""
                analysis["reason"] = f"✨【売り切れ後の再出現！】格安チケットが復活！通常より約{round(discount_rate)}% OFF（-{int(drop_amount):,}円安）{budget_txt}"
                return True, analysis

            # 3. 最後に通知してから24時間以上経過している場合（1日1回のリマインド）➔ 通知
            if now - last_notified >= timedelta(hours=24):
                return True, analysis

            # 上記以外（同じ格安価格帯のまま売れ残っている場合）➔ 通知ラッシュを防ぐためスキップ
            return False, analysis

        return True, analysis

    def record_flight(self, destination: str, route_key: str, price: float, flight_info: dict, notified: bool = False):
        """価格情報を記録・学習サンプルに追加"""
        now = datetime.now().isoformat()
        record = self.history.get(route_key, {
            "min_price": price,
            "first_seen": now,
            "price_samples": [],
        })

        samples = record.get("price_samples", [])
        samples.append(price)
        if len(samples) > 30:
            samples.pop(0)
        record["price_samples"] = samples

        record["last_price"] = price
        record["last_seen"] = now
        record["flight_info"] = flight_info

        if price < record.get("min_price", float("inf")):
            record["min_price"] = price

        typical_price = self.get_typical_price(destination, route_key)
        last_notified_price = record.get("last_notified_price", float("inf"))

        if notified:
            record["last_notified_at"] = now
            record["last_notified_price"] = price
            record["sold_out_detected"] = False  # 通知したばかりなので売り切れフラグをリセット
        else:
            # 格安枠が売り切れて通常相場に戻った、または大幅値上がりした場合を検知
            if price >= typical_price * 0.70 or (last_notified_price != float("inf") and price >= last_notified_price + 5000):
                record["sold_out_detected"] = True
                record["sold_out_at"] = now

        self.history[route_key] = record
        self.save()

    @staticmethod
    def get_airline_name(code: str) -> str:
        return AIRLINE_NAMES.get(code, code)

import os
import re
import urllib.parse
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

try:
    from fast_flights import FlightData, Passengers, get_flights
    FAST_FLIGHTS_AVAILABLE = True
except Exception as e:
    FAST_FLIGHTS_AVAILABLE = False
    print(f"⚠️ fast-flights インポート失敗: {e}")


def clean_price_to_int(price_str: str) -> Optional[int]:
    """価格文字列 (例: '¥39394' や '39,394円') から数値を抽出"""
    if not price_str:
        return None
    numbers = re.sub(r"[^\d]", "", price_str)
    return int(numbers) if numbers else None


class FlightChecker:
    """Google Flights等を直接検索し、APIキー不要でリアルタイム価格を取得するクラス"""

    def __init__(self):
        pass

    @staticmethod
    def build_google_flights_url(origin: str, destination: str, dep_date: str, ret_date: Optional[str] = None) -> str:
        """Google Flightsの直接検索・予約画面URLを生成"""
        query = f"Flights to {destination} from {origin} on {dep_date}"
        if ret_date:
            query += f" through {ret_date}"
        encoded_query = urllib.parse.quote(query)
        return f"https://www.google.com/travel/flights?q={encoded_query}&curr=JPY"

    def search_round_trip(
        self,
        origin: str,
        destination: str,
        dep_date: str,
        ret_date: str,
        max_results: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        APIキー不要でGoogle Flightsから往復最安値をリアルタイム取得
        """
        if not FAST_FLIGHTS_AVAILABLE:
            print("⚠️ fast-flights ライブラリが利用できません")
            return []

        try:
            result = get_flights(
                flight_data=[
                    FlightData(date=dep_date, from_airport=origin, to_airport=destination),
                    FlightData(date=ret_date, from_airport=destination, to_airport=origin),
                ],
                trip="round-trip",
                seat="economy",
                passengers=Passengers(adults=1),
            )

            if not result or not result.flights:
                return []

            offers = []
            for flight in result.flights[:max_results]:
                price_num = clean_price_to_int(flight.price)
                if not price_num:
                    continue

                offers.append({
                    "price": price_num,
                    "currency": "JPY",
                    "origin": origin,
                    "destination": destination,
                    "dep_date": dep_date,
                    "ret_date": ret_date,
                    "airline_name": flight.name,
                    "carriers": [flight.name],
                    "google_flights_url": self.build_google_flights_url(origin, destination, dep_date, ret_date),
                })

            offers.sort(key=lambda x: x["price"])
            return offers

        except Exception as e:
            # ネットワークエラーや一時的タイムアウト時のエラーハンドリング
            print(f"⚠️ 検索エラー [{origin} -> {destination} ({dep_date}〜{ret_date})]: {e}")
            return []

    def get_mock_deals(self, routes: list, origin: str) -> List[Dict[str, Any]]:
        """デモ動作確認用のモックデータ"""
        base_date = datetime.now() + timedelta(days=28)
        sample_scenarios = {
            "TPE": {"price": 18200, "airline": "エアアジアX"},
            "BKK": {"price": 28500, "airline": "タイ・エアアジアX"},
            "OKA": {"price": 11800, "airline": "Peach(ピーチ)"},
            "IST": {"price": 79000, "airline": "ターキッシュエアラインズ"},
        }

        deals = []
        for r in routes:
            dest = r["destination"]
            trip_day = r.get("trip_days", [3])[0]
            dep_date = base_date.strftime("%Y-%m-%d")
            ret_date = (base_date + timedelta(days=trip_day)).strftime("%Y-%m-%d")

            scenario = sample_scenarios.get(dest)
            if not scenario:
                continue

            deals.append({
                "price": scenario["price"],
                "currency": "JPY",
                "origin": origin,
                "destination": dest,
                "name": r.get("name", dest),
                "category": r.get("category", ""),
                "dep_date": dep_date,
                "ret_date": ret_date,
                "airline_name": scenario["airline"],
                "carriers": [scenario["airline"]],
                "google_flights_url": self.build_google_flights_url(origin, dest, dep_date, ret_date),
            })
        return deals

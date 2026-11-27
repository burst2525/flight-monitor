import os
import re
import urllib.parse
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

try:
    from fast_flights import FlightData, Passengers
    from fast_flights.flights_impl import TFSData
    from fast_flights.core import get_flights_from_filter
    FAST_FLIGHTS_AVAILABLE = True
except Exception as e:
    FAST_FLIGHTS_AVAILABLE = False
    print(f"⚠️ fast-flights インポート失敗: {e}")


def clean_price_to_int(price_str: str) -> Optional[int]:
    """
    価格文字列 (例: '¥39,394' や '$141') から日本円の数値を正確に抽出
    """
    if not price_str:
        return None

    is_usd = "$" in price_str
    numbers = re.sub(r"[^\d]", "", price_str)
    if not numbers:
        return None

    val = int(numbers)
    # 米国サーバー等で万が一USD($)で返ってきた場合の自動円換算 (1 USD = 約155 JPY)
    if is_usd:
        val = int(val * 155)

    return val


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
        return f"https://www.google.com/travel/flights?q={encoded_query}&curr=JPY&hl=ja"

    def search_round_trip(
        self,
        origin: str,
        destination: str,
        dep_date: str,
        ret_date: str,
        max_results: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        APIキー不要でGoogle Flightsから往復最安値をリアルタイム取得（日本円・JPY強制指定）
        """
        if not FAST_FLIGHTS_AVAILABLE:
            print("⚠️ fast-flights ライブラリが利用できません")
            return []

        try:
            tfs = TFSData.from_interface(
                flight_data=[
                    FlightData(date=dep_date, from_airport=origin, to_airport=destination),
                    FlightData(date=ret_date, from_airport=destination, to_airport=origin),
                ],
                trip="round-trip",
                seat="economy",
                passengers=Passengers(adults=1),
            )

            # 通貨にJPY(日本円)を明示的に指定！
            result = get_flights_from_filter(tfs, currency="JPY")

            if not result or not result.flights:
                return []

            offers = []
            for flight in result.flights[:max_results]:
                price_num = clean_price_to_int(flight.price)
                if not price_num:
                    continue

                stops_num = flight.stops if isinstance(flight.stops, int) else 0
                stops_text = "✈️ 直行便" if stops_num == 0 else f"🔄 経由 {stops_num}回"

                offers.append({
                    "price": price_num,
                    "currency": "JPY",
                    "origin": origin,
                    "destination": destination,
                    "dep_date": dep_date,
                    "ret_date": ret_date,
                    "airline_name": flight.name,
                    "stops": stops_num,
                    "stops_text": stops_text,
                    "duration": flight.duration or "",
                    "carriers": [flight.name],
                    "google_flights_url": self.build_google_flights_url(origin, destination, dep_date, ret_date),
                })

            offers.sort(key=lambda x: x["price"])
            return offers

        except Exception as e:
            print(f"⚠️ 検索エラー [{origin} -> {destination} ({dep_date}〜{ret_date})]: {e}")
            return []

    def search_one_way(
        self,
        origin: str,
        destination: str,
        dep_date: str,
        max_results: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        片道フライトをGoogle Flightsからリアルタイム取得（日本円・JPY）
        """
        if not FAST_FLIGHTS_AVAILABLE:
            return []

        try:
            tfs = TFSData.from_interface(
                flight_data=[
                    FlightData(date=dep_date, from_airport=origin, to_airport=destination),
                ],
                trip="one-way",
                seat="economy",
                passengers=Passengers(adults=1),
            )

            result = get_flights_from_filter(tfs, currency="JPY")
            if not result or not result.flights:
                return []

            offers = []
            for flight in result.flights[:max_results]:
                price_num = clean_price_to_int(flight.price)
                if not price_num:
                    continue

                stops_num = flight.stops if isinstance(flight.stops, int) else 0
                stops_text = "✈️ 直行便" if stops_num == 0 else f"🔄 経由 {stops_num}回"

                offers.append({
                    "price": price_num,
                    "currency": "JPY",
                    "origin": origin,
                    "destination": destination,
                    "dep_date": dep_date,
                    "airline_name": flight.name,
                    "stops": stops_num,
                    "stops_text": stops_text,
                    "duration": flight.duration or "",
                    "carriers": [flight.name],
                    "google_flights_url": self.build_google_flights_url(origin, destination, dep_date),
                })

            offers.sort(key=lambda x: x["price"])
            return offers

        except Exception as e:
            print(f"⚠️ 片道検索エラー [{origin} -> {destination} ({dep_date})]: {e}")
            return []

    def search_open_jaw(
        self,
        origin: str,
        outbound_dest: str,
        inbound_origin: str,
        final_dest: str,
        dep_date: str,
        ret_date: str,
        one_way_cache: Optional[dict] = None,
    ) -> List[Dict[str, Any]]:
        """
        周遊（オープンジョー）航空券を検索:
        行き: origin -> outbound_dest (dep_date)
        帰り: inbound_origin -> final_dest (ret_date)
        """
        cache = one_way_cache if one_way_cache is not None else {}

        out_key = (origin, outbound_dest, dep_date)
        if out_key not in cache:
            cache[out_key] = self.search_one_way(origin, outbound_dest, dep_date)
        outbound_offers = cache[out_key]

        in_key = (inbound_origin, final_dest, ret_date)
        if in_key not in cache:
            cache[in_key] = self.search_one_way(inbound_origin, final_dest, ret_date)
        inbound_offers = cache[in_key]

        if not outbound_offers or not inbound_offers:
            return []

        best_out = outbound_offers[0]
        best_in = inbound_offers[0]

        total_price = best_out["price"] + best_in["price"]
        airline_name = best_out["airline_name"] if best_out["airline_name"] == best_in["airline_name"] else f"{best_out['airline_name']} / {best_in['airline_name']}"
        stops_text = f"行: {best_out['stops_text']} / 帰: {best_in['stops_text']}"
        duration_text = f"行: {best_out['duration']}, 帰: {best_in['duration']}"

        # Google Flights 周遊用URL
        query = f"Flights from {origin} to {outbound_dest} on {dep_date} and from {inbound_origin} to {final_dest} on {ret_date}"
        encoded_query = urllib.parse.quote(query)
        multi_city_url = f"https://www.google.com/travel/flights?q={encoded_query}&curr=JPY&hl=ja"

        return [{
            "price": total_price,
            "currency": "JPY",
            "origin": origin,
            "destination": f"{outbound_dest}_{inbound_origin}",
            "dep_date": dep_date,
            "ret_date": ret_date,
            "airline_name": airline_name,
            "stops_text": stops_text,
            "duration": duration_text,
            "carriers": [best_out["airline_name"], best_in["airline_name"]],
            "google_flights_url": multi_city_url,
            "outbound": best_out,
            "inbound": best_in,
            "is_open_jaw": True,
        }]

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

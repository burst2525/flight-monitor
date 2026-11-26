import argparse
import os
import sys
import yaml
from datetime import datetime, timedelta
from dotenv import load_dotenv

from notifier import NtfyNotifier
from history_manager import PriceHistoryManager
from flight_checker import FlightChecker


def load_config(config_path: str = "config.yaml") -> dict:
    if not os.path.exists(config_path):
        print(f"❌ 設定ファイルが見つかりません: {config_path}")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def generate_gw_dates(gw_cfg: dict, trip_days_list: list) -> list:
    """ゴールデンウィーク期間の最適な出発・帰国日ペアを生成"""
    deps = gw_cfg.get("departure_dates", [])
    rets = gw_cfg.get("return_dates", [])
    valid_pairs = []

    for dep_str in deps:
        dep = datetime.strptime(dep_str, "%Y-%m-%d")
        for ret_str in rets:
            ret = datetime.strptime(ret_str, "%Y-%m-%d")
            stay_days = (ret - dep).days
            # 路線の希望日数と合致するGWペアを抽出
            if stay_days in trip_days_list:
                valid_pairs.append((dep_str, ret_str, True))  # TrueはGWフラグ

    # もし厳密に一致しない場合でも、GW期間内の妥当なペアをフォールバックとして採用
    if not valid_pairs:
        for dep_str in deps[:2]:
            dep = datetime.strptime(dep_str, "%Y-%m-%d")
            for days in trip_days_list[:2]:
                ret = dep + timedelta(days=days)
                valid_pairs.append((dep_str, ret.strftime("%Y-%m-%d"), True))

    return valid_pairs


def generate_regular_dates(start_days: int, end_days: int, trip_days_list: list) -> list:
    """通常期のサンプリング日程"""
    dates = []
    today = datetime.now()
    for d in range(start_days, end_days, 10):
        dep = today + timedelta(days=d)
        for trip_days in trip_days_list[:1]:
            ret = dep + timedelta(days=trip_days)
            dates.append((dep.strftime("%Y-%m-%d"), ret.strftime("%Y-%m-%d"), False))
    return dates


def run_check(config: dict, is_demo: bool = False, max_routes: int = 5):
    load_dotenv()

    # 1. 通知クラス
    notif_cfg = config.get("notification", {})
    topic = os.getenv("NTFY_TOPIC", notif_cfg.get("topic", "flight-alert-osaka-hiroki"))
    server = notif_cfg.get("server", "https://ntfy.sh")
    default_priority = notif_cfg.get("priority", "high")
    notifier = NtfyNotifier(topic=topic, server=server, default_priority=default_priority)

    # 2. 履歴・相場判定
    history = PriceHistoryManager()

    # 3. 判定ルール
    alert_cfg = config.get("alert_criteria", {})
    discount_threshold = alert_cfg.get("discount_threshold_percent", 25.0)
    cooldown_hours = alert_cfg.get("cooldown_hours", 8)

    # 4. フライトチェッカー
    checker = FlightChecker()

    origin = config.get("origin", {}).get("code", "KIX")
    origin_name = config.get("origin", {}).get("name", "大阪(関空)")
    routes = config.get("routes", [])

    gw_cfg = config.get("gw_focus", {})
    gw_enabled = gw_cfg.get("enabled", True)

    print(f"✈️ 航空券リアルタイム監視開始 [拠点: {origin_name}]")
    if gw_enabled:
        print("🎏 【ゴールデンウィーク(2027年4月下旬〜5月上旬)重点監視中】")
    print(f"📊 格安判定基準: 通常相場より {discount_threshold}% 以上の大幅下落・セールを検知")
    print(f"📡 iPhone通知トピック: {topic}")

    found_deals = []

    if is_demo:
        print("ℹ️ デモモードでメガセール通知のシミュレーションを実行します。")
        mock_deals = checker.get_mock_deals(routes, origin)
        for deal in mock_deals:
            dest = deal["destination"]
            route_key = f"{deal['origin']}_{dest}_{deal['dep_date']}_{deal['ret_date']}"
            should_notify, analysis = history.evaluate_deal(
                dest, route_key, deal["price"], discount_threshold_percent=discount_threshold, cooldown_hours=cooldown_hours
            )
            if should_notify:
                deal.update(analysis)
                found_deals.append(deal)
                history.record_flight(dest, route_key, deal["price"], deal, notified=True)
    else:
        # 本番：Googleフライトからリアルタイム最新価格を取得！
        for route in routes[:max_routes]:
            dest = route["destination"]
            dest_name = route.get("name", dest)
            trip_days = route.get("trip_days", [3])

            search_dates = []
            if gw_enabled:
                gw_pairs = generate_gw_dates(gw_cfg, trip_days)
                search_dates.extend(gw_pairs[:4])  # GW日程を優先

            # 通常期の日程も少し補完
            window = config.get("search_window", {})
            start_days = window.get("start_days_from_now", 14)
            end_days = window.get("end_days_from_now", 60)
            regular_pairs = generate_regular_dates(start_days, end_days, trip_days)
            search_dates.extend(regular_pairs[:1])

            typical = history.get_typical_price(dest)
            print(f"🔍 検索中: {origin_name} ➔ {dest_name}({dest}) [相場: 約{int(typical):,}円] ...")

            for dep_date, ret_date, is_gw in search_dates:
                offers = checker.search_round_trip(origin, dest, dep_date, ret_date)
                for offer in offers:
                    price = offer["price"]
                    airline = offer.get("airline_name", "航空会社")
                    route_key = f"{origin}_{dest}_{dep_date}_{ret_date}"

                    # 相場と比較して大幅値下がりか判定
                    # ※GW期間は通常期の相場でも十分安いため、GWはしきい値を少し柔軟に判定
                    gw_discount_threshold = max(15.0, discount_threshold - 5.0) if is_gw else discount_threshold
                    should_notify, analysis = history.evaluate_deal(
                        dest, route_key, price, discount_threshold_percent=gw_discount_threshold, cooldown_hours=cooldown_hours
                    )
                    
                    history.record_flight(dest, route_key, price, offer, notified=should_notify)

                    gw_tag = "🎏[GW] " if is_gw else ""
                    if should_notify:
                        deal_info = {
                            "price": int(price),
                            "currency": "JPY",
                            "origin": origin,
                            "destination": dest,
                            "name": dest_name,
                            "category": route.get("category", ""),
                            "dep_date": dep_date,
                            "ret_date": ret_date,
                            "airline_name": airline,
                            "stops_text": offer.get("stops_text", "直行便"),
                            "duration": offer.get("duration", ""),
                            "is_gw": is_gw,
                            "google_flights_url": offer["google_flights_url"],
                        }
                        deal_info.update(analysis)
                        found_deals.append(deal_info)
                        print(f"  👉 格安検知！ {gw_tag}{dest_name}: {price:,}円 ({airline})")
                    else:
                        print(f"  ・ {gw_tag}{dep_date}〜{ret_date}: {price:,}円 ({airline}) - 通常相場内")

    # 5. 格安・メガセール検知時のiPhone通知送信
    if found_deals:
        print(f"\n🎉 {len(found_deals)} 件の大幅値下げ・格安チケットを検知しました！iPhoneへ通知します...")
        for deal in found_deals:
            is_mega = deal.get("is_mega_deal", False)
            is_gw = deal.get("is_gw", False)

            if is_gw:
                badge = "🎏🚨【GWメガセール!】" if is_mega else "🎏✈️【GW格安検知】"
            else:
                badge = "🚨【メガセール!】" if is_mega else "✈️【格安検知】"

            stops_info = deal.get("stops_text", "")
            duration_info = f" (所要: {deal['duration']})" if deal.get("duration") else ""
            flight_type_line = f"🛫 運航: {deal.get('airline_name', '航空会社')} 【{stops_info}】{duration_info}\n"

            title = f"{badge} {origin_name} ➔ {deal['name']} {deal['price']:,}円"
            gw_note = "※超高騰するゴールデンウィークの格安枠です！\n" if is_gw else ""
            body = (
                f"{deal.get('reason', '')}\n"
                f"{gw_note}"
                f"💰 往復総額: {deal['price']:,}円 (通常相場: 約{deal['typical_price']:,}円)\n"
                f"🏷 割引率: 約{deal['discount_rate']}% OFF (-{deal['drop_amount']:,}円)\n"
                f"{flight_type_line}"
                f"📅 日程: {deal['dep_date']} 〜 {deal['ret_date']}\n"
                f"👉 タップしてGoogleフライトで予約画面を開く"
            )

            priority = "urgent" if (is_mega or is_gw) else "high"
            tags = ["airplane", "flags", "fire"] if is_gw else ["airplane", "sparkles"]

            notifier.send(
                title=title,
                message=body,
                click_url=deal["google_flights_url"],
                priority=priority,
                tags=tags,
            )
    else:
        print("\nℹ️ 今回の巡回では大幅に下がったフライトは見つかりませんでした。次回巡回時に再チェックします。")


def main():
    parser = argparse.ArgumentParser(description="格安航空券監視＆iPhone通知システム")
    parser.add_argument("--test-notify", action="store_true", help="iPhoneへの通知テストを送信")
    parser.add_argument("--demo", action="store_true", help="メガセール検知のシミュレーション")
    parser.add_argument("--config", default="config.yaml", help="設定ファイルのパス")
    parser.add_argument("--all-routes", action="store_true", help="全路線をくまなくチェック")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.test_notify:
        notif_cfg = config.get("notification", {})
        topic = os.getenv("NTFY_TOPIC", notif_cfg.get("topic", "flight-alert-osaka-hiroki"))
        server = notif_cfg.get("server", "https://ntfy.sh")
        notifier = NtfyNotifier(topic=topic, server=server)
        print(f"📲 トピック '{topic}' に接続テスト通知を送信中...")
        notifier.test_notification()
        return

    max_routes = len(config.get("routes", [])) if args.all_routes else 4
    run_check(config, is_demo=args.demo, max_routes=max_routes)


if __name__ == "__main__":
    main()

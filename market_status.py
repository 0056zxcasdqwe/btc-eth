import time
import requests
import pandas as pd
from datetime import datetime
from collections import deque

# ==================== 配置区 ====================
SERVERCHAN_SENDKEY = "SCT440554TBR9un4ZZPUOu6r28LJvNDpY8"

SYMBOLS = ["BTC-USDT", "ETH-USDT"]
CHECK_INTERVAL = 20
MIN_BUY_SELL_RATIO = 4.0
MIN_SELL_BUY_RATIO = 4.0

NEAR_LOWER = {
    "15m": 0.12,
    "5m": 0.10,
    "3m": 0.08
}
NEAR_UPPER = {
    "15m": 0.12,
    "5m": 0.10,
    "3m": 0.08
}

SIGNAL_COOLDOWN = 180
PRICE_DIFF_LIMIT = 0.15
BBW_RANGE_THRESHOLD = 2.0

# 每个币种独立状态
states = {
    "BTC-USDT": {
        "pending": deque(),
        "stats_3m": {"win": 0, "total": 0},
        "stats_5m": {"win": 0, "total": 0},
        "last_long_price": 0,
        "last_short_price": 0,
        "last_long_time": 0,
        "last_short_time": 0,
    },
    "ETH-USDT": {
        "pending": deque(),
        "stats_3m": {"win": 0, "total": 0},
        "stats_5m": {"win": 0, "total": 0},
        "last_long_price": 0,
        "last_short_price": 0,
        "last_long_time": 0,
        "last_short_time": 0,
    }
}

def send_wechat(title: str, content: str):
    url = f"https://sctapi.ftqq.com/{SERVERCHAN_SENDKEY}.send"
    data = {"title": title, "desp": content}
    try:
        resp = requests.post(url, data=data, timeout=10)
        print("微信提醒发送成功" if resp.json().get("code") == 0 else f"发送失败: {resp.text}")
    except Exception as e:
        print(f"微信发送异常: {e}")

def get_okx_orderbook(symbol):
    try:
        url = f"https://www.okx.com/api/v5/market/books?instId={symbol}&sz=10"
        data = requests.get(url, timeout=5).json()
        if data.get("code") != "0" or not data.get("data"):
            return 0, 0
        bids = sum(float(p) * float(q) for p, q, _, _ in data["data"][0]["bids"])
        asks = sum(float(p) * float(q) for p, q, _, _ in data["data"][0]["asks"])
        return bids, asks
    except Exception as e:
        print(f"{symbol} 订单簿错误: {e}")
        return 0, 0

def get_okx_klines(symbol, interval="15m", limit=100):
    try:
        url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar={interval}&limit={limit}"
        data = requests.get(url, timeout=5).json()
        if data.get("code") != "0" or not data.get("data"):
            raise ValueError("K线数据异常")
        rows = data["data"][::-1]
        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "vol", "volCcy", "volCcyQuote", "confirm"])
        df["close"] = df["close"].astype(float)
        return df
    except Exception as e:
        print(f"{symbol} {interval} K线失败: {e}")
        return None

def get_current_price(symbol):
    try:
        url = f"https://www.okx.com/api/v5/market/ticker?instId={symbol}"
        data = requests.get(url, timeout=5).json()
        if data.get("code") == "0" and data.get("data"):
            return float(data["data"][0]["last"])
    except:
        pass
    return None

def calculate_bollinger(df, period=20, std=2):
    df = df.copy()
    df["ma"] = df["close"].rolling(period).mean()
    df["std"] = df["close"].rolling(period).std()
    df["upper"] = df["ma"] + std * df["std"]
    df["lower"] = df["ma"] - std * df["std"]
    return df

def get_bb_info(symbol, interval):
    df = get_okx_klines(symbol, interval)
    if df is None or len(df) < 30:
        return None
    df = calculate_bollinger(df)
    latest = df.iloc[-1]
    price = latest["close"]
    lower = latest["lower"]
    upper = latest["upper"]
    mid = latest["ma"]
    dist_lower = (price - lower) / price * 100 if price > 0 else 999
    dist_upper = (upper - price) / price * 100 if price > 0 else 999
    bbw = (upper - lower) / mid * 100 if mid > 0 else 999
    is_ranging = bbw < BBW_RANGE_THRESHOLD
    return {
        "price": price,
        "lower": lower,
        "upper": upper,
        "mid": mid,
        "dist_lower": dist_lower,
        "dist_upper": dist_upper,
        "bbw": bbw,
        "is_ranging": is_ranging
    }

def check_pending_signals(symbol):
    state = states[symbol]
    now = datetime.now()
    current_price = get_current_price(symbol)
    if current_price is None:
        return

    remaining = deque()
    name = "BTC" if "BTC" in symbol else "ETH"
    for sig in state["pending"]:
        elapsed = (now - sig["time"]).total_seconds()
        direction_text = "做多" if sig["direction"] == "long" else "做空"

        if not sig["checked_3m"] and elapsed >= 180:
            win = (current_price > sig["price"]) if sig["direction"] == "long" else (current_price < sig["price"])
            state["stats_3m"]["total"] += 1
            if win:
                state["stats_3m"]["win"] += 1
            sig["checked_3m"] = True
            rate = state["stats_3m"]["win"] / state["stats_3m"]["total"] * 100
            result = "成功 ✅" if win else "失败 ❌"
            title = f"【3分钟验证】{name} {direction_text}信号"
            content = f"**结果**：{result}\n**开仓价**：{sig['price']:.2f}\n**当前价**：{current_price:.2f}\n**3分钟成功率**：{rate:.1f}%（{state['stats_3m']['win']}/{state['stats_3m']['total']}）"
            send_wechat(title, content)
            print(f">>> {name} 3分钟验证: {result}")

        if not sig["checked_5m"] and elapsed >= 300:
            win = (current_price > sig["price"]) if sig["direction"] == "long" else (current_price < sig["price"])
            state["stats_5m"]["total"] += 1
            if win:
                state["stats_5m"]["win"] += 1
            sig["checked_5m"] = True
            rate = state["stats_5m"]["win"] / state["stats_5m"]["total"] * 100
            result = "成功 ✅" if win else "失败 ❌"
            title = f"【5分钟验证】{name} {direction_text}信号"
            content = f"**结果**：{result}\n**开仓价**：{sig['price']:.2f}\n**当前价**：{current_price:.2f}\n**5分钟成功率**：{rate:.1f}%（{state['stats_5m']['win']}/{state['stats_5m']['total']}）"
            send_wechat(title, content)
            print(f">>> {name} 5分钟验证: {result}")

        if not (sig["checked_3m"] and sig["checked_5m"]):
            remaining.append(sig)

    state["pending"] = remaining

def get_success_rate_text(symbol):
    s = states[symbol]
    r3 = s["stats_3m"]["win"] / s["stats_3m"]["total"] * 100 if s["stats_3m"]["total"] > 0 else 0
    r5 = s["stats_5m"]["win"] / s["stats_5m"]["total"] * 100 if s["stats_5m"]["total"] > 0 else 0
    return f"3分钟成功率: {r3:.1f}% ({s['stats_3m']['win']}/{s['stats_3m']['total']})\n5分钟成功率: {r5:.1f}% ({s['stats_5m']['win']}/{s['stats_5m']['total']})"

def get_range_tag(r3, r5, r15):
    count = sum([r3, r5, r15])
    if count == 3:
        return "【超强震荡信号】"
    elif count == 2:
        return "【强震荡信号】"
    return ""

print("=" * 50)
print("BTC + ETH 合并监控已启动（任意两个周期满足即可）")
print("=" * 50)

while True:
    try:
        for symbol in SYMBOLS:
            name = "BTC" if "BTC" in symbol else "ETH"
            state = states[symbol]

            check_pending_signals(symbol)

            ok_bids, ok_asks = get_okx_orderbook(symbol)
            buy_sell_ratio = ok_bids / ok_asks if ok_asks > 0 else 0
            sell_buy_ratio = ok_asks / ok_bids if ok_bids > 0 else 0

            bb_15 = get_bb_info(symbol, "15m")
            bb_5  = get_bb_info(symbol, "5m")
            bb_3  = get_bb_info(symbol, "3m")

            if bb_15 is None or bb_5 is None or bb_3 is None:
                print(f"{name} 布林带数据获取失败，跳过")
                continue

            price = bb_15["price"]
            now_str = datetime.now().strftime("%H:%M:%S")
            now_ts = time.time()

            # 震荡判断
            r15 = bb_15["is_ranging"]
            r5  = bb_5["is_ranging"]
            r3  = bb_3["is_ranging"]
            range_tag = get_range_tag(r3, r5, r15)

            # 接近下轨判断（任意两个）
            near_lower_15 = bb_15["dist_lower"] < NEAR_LOWER["15m"] and price < bb_15["mid"]
            near_lower_5  = bb_5["dist_lower"] < NEAR_LOWER["5m"]
            near_lower_3  = bb_3["dist_lower"] < NEAR_LOWER["3m"]
            near_lower_count = sum([near_lower_15, near_lower_5, near_lower_3])
            long_signal = (buy_sell_ratio >= MIN_BUY_SELL_RATIO) and near_lower_count >= 2

            # 接近上轨判断（任意两个）
            near_upper_15 = bb_15["dist_upper"] < NEAR_UPPER["15m"] and price > bb_15["mid"]
            near_upper_5  = bb_5["dist_upper"] < NEAR_UPPER["5m"]
            near_upper_3  = bb_3["dist_upper"] < NEAR_UPPER["3m"]
            near_upper_count = sum([near_upper_15, near_upper_5, near_upper_3])
            short_signal = (sell_buy_ratio >= MIN_SELL_BUY_RATIO) and near_upper_count >= 2

            rate_text = get_success_rate_text(symbol)
            print(f"[{now_str}] {name}:{price:.2f} | 下轨:{bb_15['dist_lower']:.2f}% | 上轨:{bb_15['dist_upper']:.2f}% | 买/卖:{buy_sell_ratio:.2f} | 接近数:下{near_lower_count}/上{near_upper_count}")
            print(f"       {rate_text}")

            # 做多信号
            if long_signal:
                price_diff = abs(price - state["last_long_price"]) / price * 100 if state["last_long_price"] > 0 else 999
                if (now_ts - state["last_long_time"] > SIGNAL_COOLDOWN) and (price_diff > PRICE_DIFF_LIMIT):
                    state["pending"].append({
                        "time": datetime.now(),
                        "price": price,
                        "direction": "long",
                        "checked_3m": False,
                        "checked_5m": False
                    })
                    title = f"{range_tag}【{name}做多信号】事件合约看涨"
                    content = f"""
**时间**：{now_str}
**{name}当前价格**：{price:.2f}

**距离下轨**：
- 15分钟：{bb_15['dist_lower']:.2f}% {'✓' if near_lower_15 else ''}
- 5分钟：{bb_5['dist_lower']:.2f}% {'✓' if near_lower_5 else ''}
- 3分钟：{bb_3['dist_lower']:.2f}% {'✓' if near_lower_3 else ''}

**欧意买/卖比**：{buy_sell_ratio:.2f}
**满足周期数**：{near_lower_count}个

**历史成功率**：
{rate_text}

建议：最小仓位开【看涨】3分钟或5分钟事件合约
"""
                    send_wechat(title, content)
                    print(f">>> {name}做多信号已推送！{range_tag}")
                    state["last_long_time"] = now_ts
                    state["last_long_price"] = price
                else:
                    print(f"（{name}做多信号被防重复过滤）")

            # 做空信号
            if short_signal:
                price_diff = abs(price - state["last_short_price"]) / price * 100 if state["last_short_price"] > 0 else 999
                if (now_ts - state["last_short_time"] > SIGNAL_COOLDOWN) and (price_diff > PRICE_DIFF_LIMIT):
                    state["pending"].append({
                        "time": datetime.now(),
                        "price": price,
                        "direction": "short",
                        "checked_3m": False,
                        "checked_5m": False
                    })
                    title = f"{range_tag}【{name}做空信号】事件合约看跌"
                    content = f"""
**时间**：{now_str}
**{name}当前价格**：{price:.2f}

**距离上轨**：
- 15分钟：{bb_15['dist_upper']:.2f}% {'✓' if near_upper_15 else ''}
- 5分钟：{bb_5['dist_upper']:.2f}% {'✓' if near_upper_5 else ''}
- 3分钟：{bb_3['dist_upper']:.2f}% {'✓' if near_upper_3 else ''}

**欧意卖/买比**：{sell_buy_ratio:.2f}
**满足周期数**：{near_upper_count}个

**历史成功率**：
{rate_text}

建议：最小仓位开【看跌】3分钟或5分钟事件合约
"""
                    send_wechat(title, content)
                    print(f">>> {name}做空信号已推送！{range_tag}")
                    state["last_short_time"] = now_ts
                    state["last_short_price"] = price
                else:
                    print(f"（{name}做空信号被防重复过滤）")

            if not long_signal and not short_signal:
                print(f"{name} 暂无信号")

    except Exception as e:
        print(f"主循环错误: {e}")
        time.sleep(10)

    time.sleep(CHECK_INTERVAL)

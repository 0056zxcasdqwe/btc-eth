import time
import requests
import pandas as pd
from datetime import datetime

# ==================== 配置区 ====================
SERVERCHAN_SENDKEY = "SCT440554TBR9un4ZZPUOu6r28LJvNDpY8"

SYMBOLS = ["BTC-USDT", "ETH-USDT"]
CHECK_INTERVAL = 30                # 每30秒检查一次
PUSH_INTERVAL = 300                # 每5分钟推送一次微信
BBW_RANGE_THRESHOLD = 2.0          # BBW < 2.0 视为震荡
NEAR_BAND_THRESHOLD = 0.25         # 距离上下轨 < 0.25% 视为靠近轨道

last_push_time = 0

def send_wechat(title: str, content: str):
    url = f"https://sctapi.ftqq.com/{SERVERCHAN_SENDKEY}.send"
    data = {"title": title, "desp": content}
    try:
        resp = requests.post(url, data=data, timeout=10)
        print("微信推送成功" if resp.json().get("code") == 0 else f"推送失败: {resp.text}")
    except Exception as e:
        print(f"微信推送异常: {e}")

def get_okx_klines(symbol, interval="15m", limit=50):
    try:
        url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar={interval}&limit={limit}"
        data = requests.get(url, timeout=5).json()
        if data.get("code") != "0" or not data.get("data"):
            return None
        rows = data["data"][::-1]
        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "vol", "volCcy", "volCcyQuote", "confirm"])
        df["close"] = df["close"].astype(float)
        return df
    except Exception as e:
        print(f"{symbol} {interval} K线获取失败: {e}")
        return None

def analyze_bb(symbol, interval):
    df = get_okx_klines(symbol, interval)
    if df is None or len(df) < 25:
        return None

    df = df.copy()
    df["ma"] = df["close"].rolling(20).mean()
    df["std"] = df["close"].rolling(20).std()
    df["upper"] = df["ma"] + 2 * df["std"]
    df["lower"] = df["ma"] - 2 * df["std"]

    latest = df.iloc[-1]
    price = latest["close"]
    mid = latest["ma"]
    upper = latest["upper"]
    lower = latest["lower"]

    dist_lower = (price - lower) / price * 100
    dist_upper = (upper - price) / price * 100
    dist_mid = abs(price - mid) / price * 100
    bbw = (upper - lower) / mid * 100

    # 判断震荡还是趋势
    is_ranging = bbw < BBW_RANGE_THRESHOLD

    # 判断位置类型
    if dist_lower < NEAR_BAND_THRESHOLD:
        position = "偏下轨"
    elif dist_upper < NEAR_BAND_THRESHOLD:
        position = "偏上轨"
    elif dist_mid < 0.15:
        position = "中轨附近"
    else:
        position = "轨道中间"

    # 震荡类型细分
    if is_ranging:
        if position in ["偏下轨", "偏上轨"]:
            range_type = "上下轨震"
        elif position == "中轨附近":
            range_type = "中轨震"
        else:
            range_type = "区间震"
        status = f"震荡（{range_type}）"
    else:
        status = "趋势"
        range_type = "-"

    return {
        "price": price,
        "bbw": bbw,
        "dist_lower": dist_lower,
        "dist_upper": dist_upper,
        "dist_mid": dist_mid,
        "is_ranging": is_ranging,
        "position": position,
        "status": status,
        "range_type": range_type
    }

def get_symbol_report(symbol):
    result = {}
    for tf in ["3m", "5m", "15m"]:
        info = analyze_bb(symbol, tf)
        if info:
            result[tf] = info
    return result

def format_report(all_data):
    lines = []
    now = datetime.now().strftime("%H:%M:%S")
    lines.append(f"**行情状态报告**  {now}\n")

    for symbol, data in all_data.items():
        name = "BTC" if "BTC" in symbol else "ETH"
        lines.append(f"### {name}")
        if not data:
            lines.append("数据获取失败\n")
            continue

        for tf in ["3m", "5m", "15m"]:
            if tf not in data:
                continue
            d = data[tf]
            lines.append(
                f"- **{tf}**：{d['status']} | 位置:{d['position']} | "
                f"宽度:{d['bbw']:.2f}% | 下轨距:{d['dist_lower']:.2f}% | 上轨距:{d['dist_upper']:.2f}%"
            )
        lines.append("")

    return "\n".join(lines)

print("=" * 50)
print("BTC + ETH 行情状态监控已启动（支持微信推送）")
print("=" * 50)

while True:
    try:
        all_data = {}
        for symbol in SYMBOLS:
            all_data[symbol] = get_symbol_report(symbol)

        # 打印日志
        now_str = datetime.now().strftime("%H:%M:%S")
        print(f"\n[{now_str}] 行情状态：")
        for symbol, data in all_data.items():
            name = "BTC" if "BTC" in symbol else "ETH"
            print(f"  {name}:")
            for tf in ["3m", "5m", "15m"]:
                if tf in data:
                    d = data[tf]
                    print(f"    {tf}: {d['status']} | {d['position']} | BBW:{d['bbw']:.2f}%")

        # 定时推送微信
        current_time = time.time()
        if current_time - last_push_time >= PUSH_INTERVAL:
            content = format_report(all_data)
            send_wechat("【行情状态】BTC + ETH 3/5/15分钟分析", content)
            last_push_time = current_time
            print(">>> 已推送微信状态报告")

    except Exception as e:
        print(f"主循环错误: {e}")
        time.sleep(10)

    time.sleep(CHECK_INTERVAL)

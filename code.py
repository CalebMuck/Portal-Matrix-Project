import time
import rtc
import secrets
import terminalio
import displayio
from adafruit_display_text.label import Label
from adafruit_matrixportal.matrixportal import MatrixPortal

TICKERS = ["AAPL", "MSFT", "NVDA", "TSLA"]
REFRESH_MARKET_SECONDS = 120
SCROLL_SPEED =

# Market hours (ET)
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MIN  = 30
MARKET_CLOSE_HOUR = 16
MARKET_CLOSE_MIN  = 0

TZ_OFFSET = secrets.secrets.get("tz_offset_hours", -5)
TD_KEY = secrets.secrets["twelvedata_api_key"]
SYMBOLS = ",".join(TICKERS)
TD_URL = f"https://api.twelvedata.com/quote?symbol={SYMBOLS}&apikey={TD_KEY}"

GREEN = 0x00FF00
RED   = 0xFF0000
GRAY  = 0x888888
BLUE  = 0x00A0FF

mp = MatrixPortal(debug=True)
display = mp.display
root = displayio.Group()
display.root_group = root

def clear_root():
    while len(root) > 0:
        root.pop()


def http_time_sync():
    urls = [
        "https://worldtimeapi.org/api/timezone/Etc/UTC",
        "https://timeapi.io/api/Time/current/zone?timeZone=UTC",
    ]

    for attempt in range(1, 4):  # 3 tries
        for url in urls:
            try:
                print(f"TIME SYNC try {attempt} -> {url}")
                r = mp.network.fetch(url, headers={"User-Agent": "MatrixPortalS3"})
                text = r.text
                r.close()

                if "unixtime" in text:
                    import json
                    data = json.loads(text)
                    unix = int(data["unixtime"])
                    rtc.RTC().datetime = time.localtime(unix)
                    return True

                if "dateTime" in text:
                    import json
                    data = json.loads(text)
                    dt = data["dateTime"]
                    year = int(dt[0:4]); mon = int(dt[5:7]); day = int(dt[8:10])
                    hour = int(dt[11:13]); minute = int(dt[14:16]); sec = int(dt[17:19])
                    rtc.RTC().datetime = time.struct_time(
                        (year, mon, day, hour, minute, sec, -1, -1, -1)
                    )
                    return True

                print("TIME SYNC: unexpected response (not JSON I recognize)")
                print(text[:120])

            except Exception as e:
                print("TIME SYNC ERROR:", repr(e))

        time.sleep(2 * attempt)

    return False

status = Label(terminalio.FONT, text="SYNC TIME...", color=BLUE, x=0, y=12)
root.append(status)

ok = http_time_sync()
if ok:
    print("HTTP TIME OK:", time.localtime())
    status.text = "TIME OK"
else:
    print("HTTP TIME SKIPPED")
    status.text = "TIME SKIP"

time.sleep(1)
root.pop()

def local_time():
    t = time.localtime()
    hour = (t.tm_hour + TZ_OFFSET) % 24
    return t.tm_wday, hour, t.tm_min

def market_open():
    wday, hour, minute = local_time()

    if wday > 4:
        return False

    if hour < MARKET_OPEN_HOUR or (hour == MARKET_OPEN_HOUR and minute < MARKET_OPEN_MIN):
        return False

    if hour > MARKET_CLOSE_HOUR or (hour == MARKET_CLOSE_HOUR and minute >= MARKET_CLOSE_MIN):
        return False

    return True

last_prices = {s: None for s in TICKERS}

def fetch_prices():
    r = mp.network.fetch(TD_URL, headers={"User-Agent": "MatrixPortalS3"})
    data = r.json()
    r.close()

    prices = {}
    if isinstance(data, dict):
        for sym in TICKERS:
            obj = data.get(sym, {})
            p = obj.get("price") or obj.get("close")
            if p is not None:
                try:
                    prices[sym] = float(p)
                except Exception:
                    pass
    else:
        print("TD RAW:", data)

    return prices

def build_ticker(prices):
    g = displayio.Group()
    x = 64

    for sym in TICKERS:
        p = prices.get(sym)
        prev = last_prices.get(sym)

        if p is None and prev is not None:
            p = prev

        if p is None or prev is None:
            color = GRAY
            arrow = "="
        elif p > prev:
            color = GREEN
            arrow = "^"
        elif p < prev:
            color = RED
            arrow = "v"
        else:
            color = GRAY
            arrow = "="

        if p is not None:
            last_prices[sym] = p
            text = f"{sym} {p:.2f} {arrow}   "
        else:
            text = f"{sym} -- {arrow}   "

        lbl = Label(terminalio.FONT, text=text, color=color, x=x, y=12)
        g.append(lbl)
        x += lbl.bounding_box[2]

    if len(g) == 0:
        g.append(Label(terminalio.FONT, text="NO DATA   ", color=RED, x=64, y=12))

    return g

mode = None
ticker_group = None
last_fetch = -9999

def enter_closed_mode():
    global mode, ticker_group
    mode = "CLOSED"
    clear_root()

    closed = Label(terminalio.FONT, text="MARKET CLOSED           WILL RE-OPEN NEXT WEEKDAY AT 9:30AM   ", color=BLUE, x=64, y=12)
    root.append(closed)

    ticker_group = None


def enter_open_mode():
    global mode, ticker_group, last_fetch
    mode = "OPEN"
    clear_root()
    ticker_group = None
    last_fetch = -9999

if market_open():
    enter_open_mode()
else:
    enter_closed_mode()

while True:
    if market_open():
        if mode != "OPEN":
            enter_open_mode()

        now = time.monotonic()

        if ticker_group is None or (now - last_fetch >= REFRESH_MARKET_SECONDS):
            prices = {}
            try:
                prices = fetch_prices()
            except Exception as e:
                print("TD FETCH ERROR:", repr(e))

            if ticker_group is not None:
                try:
                    root.remove(ticker_group)
                except Exception:
                    pass

            ticker_group = build_ticker(prices)
            root.append(ticker_group)
            last_fetch = now

        if ticker_group is not None and len(ticker_group) > 0:
            for lbl in ticker_group:
                lbl.x -= SCROLL_SPEED

            last_lbl = ticker_group[len(ticker_group) - 1]
            if last_lbl.x + last_lbl.bounding_box[2] < 0:
                reset_x = 64
                for lbl in ticker_group:
                    lbl.x = reset_x
                    reset_x += lbl.bounding_box[2]

        time.sleep(0.02)

    else:
        if mode != "CLOSED":
            enter_closed_mode()

        closed_lbl = root[0]

        closed_lbl.x -= 1  # scroll speed

        if closed_lbl.x + closed_lbl.bounding_box[2] < 0:
            closed_lbl.x = 64

        time.sleep(0.03)

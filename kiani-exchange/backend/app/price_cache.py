import time
import logging
import aiohttp
import random

logger = logging.getLogger(__name__)

# List of proxy servers
PROXY_LIST = [
    "45.159.53.29:7401",
    "107.181.142.146:5739",
    "147.136.85.66:5982",
    "193.160.78.239:5919",
    "104.250.207.125:6523",
    "173.245.88.77:5380",
    "107.181.143.171:6302",
    "45.38.84.162:7098",
    "67.227.1.26:6307",
    "92.113.1.107:5807",
    "64.137.92.43:6242",
    "67.227.37.170:5712",
    "191.96.173.42:6055",
    "104.143.252.167:5781",
    "45.141.81.25:6085",
    "168.199.145.4:6262",
    "45.38.111.198:6113",
    "31.58.23.166:5739",
    "45.150.178.246:6118",
    "206.206.71.86:5726",
    "67.227.37.52:5594",
    "92.112.155.70:7194",
    "104.239.97.191:5944",
    "2.57.30.125:7201",
    "104.238.14.125:6510",
    "104.239.44.190:6112",
    "184.174.126.51:6343",
    "136.0.189.140:6867",
    "168.199.145.55:6313",
    "2.57.31.223:6799",
    "67.227.42.206:6183",
    "194.39.32.247:6544",
    "140.233.166.169:7202",
    "31.59.21.101:6367",
    "64.137.37.38:6628",
    "102.212.88.222:6219",
    "104.233.13.184:6179",
    "104.252.28.134:6072",
    "136.0.118.200:6572",
    "80.96.71.105:5595",
    "193.187.114.215:6230",
    "45.38.84.253:7189",
    "93.118.38.64:6208",
    "206.206.64.140:6101",
    "64.137.57.98:6107",
    "104.252.193.112:6022",
    "185.15.178.101:5785",
    "104.253.81.21:5449",
    "148.135.188.5:7037",
    "31.57.90.143:5712",
    "45.147.187.3:6376",
    "45.150.23.199:6669",
    "145.223.40.236:5806",
    "155.254.38.123:5799",
    "46.203.45.196:6219",
    "185.171.255.30:6083",
    "46.203.79.27:6553",
    "45.159.54.195:7067",
    "92.112.227.32:6204",
    "82.29.229.112:6467",
    "23.129.254.13:5995",
    "67.227.113.72:5612",
    "67.227.113.15:5555",
    "92.112.238.65:6944",
    "82.22.210.225:8067",
    "45.61.97.253:6779",
    "23.236.170.178:9211",
    "104.252.193.75:5985",
    "82.29.229.65:6420",
    "23.229.110.120:8648",
    "82.24.236.86:7896",
    "31.58.24.163:6234",
    "45.14.83.8:7986",
    "82.23.225.200:8051",
    "204.217.245.155:6746",
    "82.27.214.241:6583",
    "82.23.221.29:6359",
    "45.131.94.82:6069",
    "103.101.88.202:5926",
    "82.21.245.103:6427",
    "161.123.33.185:6208",
    "23.95.255.75:6659",
    "98.159.38.158:6458",
    "45.39.4.13:5438",
    "82.24.249.60:5897",
    "136.0.189.227:6954",
    "82.21.245.189:6513",
    "206.232.103.58:6215",
    "23.27.196.222:6591",
    "104.143.226.126:5729",
    "82.25.247.17:6351",
    "92.112.235.4:6527",
    "82.23.204.82:6914",
    "23.27.210.154:6524",
    "104.238.38.24:6292",
    "216.173.72.20:6639",
    "23.229.125.113:5382",
    "82.29.245.125:6949",
    "50.114.99.138:6879",
    "50.114.99.125:6866"
]

def get_random_proxy():
    """Get a random proxy from the list"""
    proxy = random.choice(PROXY_LIST)
    return f"http://jjebraham:Amir1234@{proxy}"

WALLEX_API_KEY = "15064|7tVDd4NDBYmATAe4lWTUQSTzj0v7ceTELEv6u6zG"
WALLEX_BASE_URL = "https://api.wallex.ir/v1"


class PriceCache:
    def __init__(self):
        self.usdt_irr = None
        self.usdt_irr_time = 0
        self.usdt_try = None
        self.usdt_try_time = 0
        self.fetch_interval = 600  # seconds

    async def _fetch_with_proxy_retry(self, url, headers=None, is_json=True, max_retries=3):
        """Helper method to fetch with proxy retry logic"""
        tried_proxies = set()
        
        for attempt in range(max_retries):
            # Get a proxy we haven't tried yet
            available_proxies = [p for p in PROXY_LIST if p not in tried_proxies]
            if not available_proxies:
                break
                
            proxy = random.choice(available_proxies)
            proxy_url = f"http://jjebraham:Amir1234@{proxy}"
            tried_proxies.add(proxy)
            
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.get(
                        url,
                        headers=headers,
                        proxy=proxy_url,
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:
                        resp.raise_for_status()
                        if is_json:
                            data = await resp.json()
                            return data
                        else:
                            text = await resp.text()
                            return text
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} with proxy {proxy} failed: {e}")
                continue
        
        raise Exception(f"All {max_retries} proxy attempts failed for {url}")

    async def fetch_usdt_irr(self) -> float:
        # Primary: flask proxy
        primary_url = "https://flask-9l1dbb.chbk.app/proxy/usdt-to-rls"
        try:
            data = await self._fetch_with_proxy_retry(primary_url, is_json=True)
            rate = data.get("usdt_to_rls")
            if rate:
                return float(rate)
            raise ValueError("no usdt_to_rls in primary response")
        except Exception as e:
            logger.warning(f"Primary USDT-IRR failed: {e}")

        # Fallback: Wallex API
        try:
            headers = {"X-API-KEY": WALLEX_API_KEY, "User-Agent": "Mozilla/5.0"}
            data = await self._fetch_with_proxy_retry(
                f"{WALLEX_BASE_URL}/markets",
                headers=headers,
                is_json=True
            )
            symbols = data.get("result", {}).get("symbols", {})
            usdt_data = symbols.get("USDTTMN")
            if not usdt_data:
                raise ValueError("USDTTMN not found in Wallex response")
            stats = usdt_data.get("stats", {})
            last_price = stats.get("lastPrice")
            if last_price:
                return float(last_price) * 10  # Convert Toman to Rial
            raise ValueError("No lastPrice in Wallex data")
        except Exception as e:
            logger.error(f"Wallex USDT-IRR fallback failed: {e}")
            raise

    async def fetch_usdt_try(self) -> float:
        url = "https://api.btcturk.com/api/v2/ticker?pairSymbol=USDTTRY"
        try:
            data = await self._fetch_with_proxy_retry(url, is_json=True)
            items = data.get("data", [])
            if items:
                return float(items[0].get("last", 0))
            raise ValueError("No data in BTCTurk response")
        except Exception as e:
            logger.error(f"USDT-TRY fetch failed: {e}")
            raise

    async def get_usdt_irr(self) -> float:
        now = time.time()
        if self.usdt_irr is None or (now - self.usdt_irr_time) > self.fetch_interval:
            self.usdt_irr = await self.fetch_usdt_irr()
            self.usdt_irr_time = now
        return self.usdt_irr

    async def get_usdt_try(self) -> float:
        now = time.time()
        if self.usdt_try is None or (now - self.usdt_try_time) > self.fetch_interval:
            self.usdt_try = await self.fetch_usdt_try()
            self.usdt_try_time = now
        return self.usdt_try


price_cache = PriceCache()

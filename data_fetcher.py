import requests
import time
import datetime
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from sina_fetcher import SinaFetcher

logger = logging.getLogger(__name__)

def _secid(code):
    """东方财富 secid：沪市(6开头/9开头)前缀1，深市前缀0"""
    return f'1.{code}' if str(code).startswith(('6', '9')) else f'0.{code}'

class StockDataFetcher:
    # 全局限流熔断：多线程共享，连续失败过多时整体退避
    _breaker_lock = threading.Lock()
    _consecutive_failures = 0
    _backoff_until = 0.0

    BREAKER_THRESHOLD = 15   # 连续失败15次触发熔断
    BREAKER_SLEEP = 20       # 熔断后暂停20秒

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
        })
        # 连接池匹配K线并发线程数，避免连接被频繁丢弃
        adapter = requests.adapters.HTTPAdapter(pool_connections=16, pool_maxsize=16, max_retries=0)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        self.timeout = 8
        self.fallback = SinaFetcher()
        self.use_fallback = False

    def _wait_for_breaker(self):
        now = time.time()
        if now < self._backoff_until:
            time.sleep(self._backoff_until - now + 0.1)

    def _record_success(self):
        with self._breaker_lock:
            self._consecutive_failures = 0

    def _record_failure(self):
        """触发熔断时返回应额外睡眠的秒数，否则返回0"""
        with self._breaker_lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.BREAKER_THRESHOLD:
                self._consecutive_failures = 0
                self._backoff_until = time.time() + self.BREAKER_SLEEP
                logger.warning(f"[限流熔断] 连续失败过多，暂停{self.BREAKER_SLEEP}秒后重试")
                return self.BREAKER_SLEEP
        return 0

    def _get_json(self, url, params, retries=3, timeout=None, hosts=None):
        """带重试的GET JSON（东方财富偶发断连，指数退避 + 多子域轮询）。
        hosts: 候选根地址列表（如 ['http://push2.eastmoney.com', 'http://82.push2.eastmoney.com']），
               url 中的根会被依次替换重试。
        """
        if hosts:
            candidates = []
            tail = url[url.index('/', url.index('://') + 3):]
            for h in hosts:
                candidates.append(h.rstrip('/') + tail)
        else:
            candidates = [url]

        last_exc = None
        for attempt in range(retries):
            self._wait_for_breaker()
            base_url = candidates[attempt % len(candidates)]
            try:
                resp = self.session.get(base_url, params=params, timeout=timeout or self.timeout)
                result = resp.json()
                self._record_success()
                return result
            except Exception as e:
                last_exc = e
                extra = self._record_failure()
                if attempt < retries - 1:
                    time.sleep(1.0 * (attempt + 1) + extra)  # 退避 + 熔断等待
        raise last_exc

    def _try_with_fallback(self, primary_func, fallback_func, func_name):
        """尝试主数据源，失败时自动降级到备选"""
        if self.use_fallback:
            logger.info(f"[数据源切换] {func_name} -> 备选(新浪)，原因: 已标记降级")
            return fallback_func()

        logger.info(f"[数据源切换] {func_name} -> 主(东方财富)，尝试请求...")
        start_time = time.time()
        result = []

        try:
            result = primary_func()
            elapsed = time.time() - start_time
            if result is not None and len(result) > 0 if isinstance(result, list) else result:
                logger.info(f"[数据源切换] {func_name} <- 主(东方财富) 成功，耗时{elapsed:.2f}s，数据量={len(result) if isinstance(result, list) else 'dict'}")
                return result
            # 主数据源返回空，尝试备选
            logger.warning(f"[数据源切换] {func_name} <- 主(东方财富) 返回空数据，耗时{elapsed:.2f}s，降级到备选")
        except Exception as e:
            elapsed = time.time() - start_time
            logger.warning(f"[数据源切换] {func_name} <- 主(东方财富) 异常: {type(e).__name__}: {e}，耗时{elapsed:.2f}s，降级到备选")

        logger.info(f"[数据源切换] {func_name} -> 备选(新浪)，尝试请求...")
        fallback_start = time.time()

        try:
            result = fallback_func()
            fallback_elapsed = time.time() - fallback_start
            if result:
                logger.info(f"[数据源切换] {func_name} <- 备选(新浪) 成功，耗时{fallback_elapsed:.2f}s，数据量={len(result) if isinstance(result, list) else 'dict'}，后续优先使用备选")
                self.use_fallback = True
                return result
            logger.warning(f"[数据源切换] {func_name} <- 备选(新浪) 返回空数据")
        except Exception as e:
            fallback_elapsed = time.time() - fallback_start
            logger.error(f"[数据源切换] {func_name} <- 备选(新浪) 异常: {type(e).__name__}: {e}，耗时{fallback_elapsed:.2f}s")

        return [] if isinstance(result, list) else {}

    def get_collection_bidding(self):
        return self._try_with_fallback(
            self._get_collection_bidding_primary,
            self.fallback.get_collection_bidding,
            "集合竞价"
        )

    def _get_collection_bidding_primary(self):
        """全市场实时行情（分页拉取，接口单页上限约100只）"""
        url = 'http://push2.eastmoney.com/api/qt/clist/get'
        # 备用编号子域，单子域被限流时自动切换
        hosts = [
            'http://push2.eastmoney.com',
            'http://82.push2.eastmoney.com',
            'http://19.push2.eastmoney.com',
            'http://48.push2.eastmoney.com',
        ]
        base_params = {
            'po': '1',
            'np': '1',
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': '2',
            'invt': '2',
            'fid': 'f3',
            'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',
            'fields': 'f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f26,f27,f28,f30,f31,f32,f33,f34,f35,f36,f37,f38,f39,f40,f41,f42,f43,f44,f45,f46,f47,f48,f49,f50,f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65'
        }

        page_size = 100
        max_pages = 80  # A股约5400只，保护上限
        all_rows = []
        seen_codes = set()
        total = None

        for pn in range(1, max_pages + 1):
            params = dict(base_params, pn=str(pn), pz=str(page_size))
            data = self._get_json(url, params, retries=5, hosts=hosts)
            if not data or not data.get('data') or not data['data'].get('diff'):
                break

            if total is None:
                total = data['data'].get('total', 0)

            page_rows = data['data']['diff']
            for row in page_rows:
                code = str(row.get('f12', ''))
                if code and code not in seen_codes:
                    seen_codes.add(code)
                    all_rows.append(row)

            if total and len(all_rows) >= total:
                break
            if len(page_rows) < page_size:
                break
            time.sleep(0.1)  # 轻微限速，避免被接口断连

        logger.info(f"[东方财富] 实时行情分页拉取完成: {len(all_rows)}只 (total={total})")
        return all_rows

    def get_stock_plates_batch(self, codes):
        return self._try_with_fallback(
            lambda: self._get_stock_plates_batch_primary(codes),
            lambda: self.fallback.get_stock_plates_batch(codes),
            "板块信息"
        )

    def _get_stock_plate_single(self, code):
        url = f'http://push2.eastmoney.com/api/qt/stock/get'
        params = {
            'secid': _secid(code),
            'fields': 'f102,f103,f104,f105'
        }
        try:
            data = self._get_json(url, params, retries=2)
            if data.get('data'):
                return {
                    'code': code,
                    'industry': data['data'].get('f102', ''),
                    'concept': data['data'].get('f103', ''),
                    'region': data['data'].get('f104', ''),
                    'market': data['data'].get('f105', '')
                }
            return {'code': code, 'industry': '', 'concept': '', 'region': '', 'market': ''}
        except Exception:
            return {'code': code, 'industry': '', 'concept': '', 'region': '', 'market': ''}

    def _get_stock_plates_batch_primary(self, codes):
        plate_info = {}
        with ThreadPoolExecutor(max_workers=20) as executor:
            future_to_code = {executor.submit(self._get_stock_plate_single, code): code for code in codes}
            for future in as_completed(future_to_code):
                result = future.result()
                plate_info[result['code']] = result
        return plate_info

    def get_kline_data_batch(self, codes, days=20):
        return self._try_with_fallback(
            lambda: self._get_kline_data_batch_primary(codes, days),
            lambda: self.fallback.get_kline_data_batch(codes, days),
            "K线数据"
        )

    def _get_kline_single(self, code, days=20):
        """获取日K线（前复权）。
        东方财富 smplmt/lmt 参数不可用（rc:102 data:null 或被忽略），
        必须传显式 beg 起始日期。多取一些自然日以覆盖周末/节假日，最后只保留最近 days 条。
        """
        url = 'http://push2his.eastmoney.com/api/qt/stock/kline/get'
        calendar_days = days * 2 + 20
        beg = (datetime.date.today() - datetime.timedelta(days=calendar_days)).strftime('%Y%m%d')
        params = {
            'secid': _secid(code),
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
            'klt': '101',
            'fqt': '1',
            'beg': beg,
            'end': '20500101',
        }
        try:
            data = self._get_json(url, params, retries=3)
            if data.get('data') and data['data'].get('klines'):
                klines = []
                for kline_str in data['data']['klines']:
                    parts = kline_str.split(',')
                    if len(parts) >= 11:
                        klines.append({
                            'date': parts[0],
                            'open': float(parts[1]),
                            'close': float(parts[2]),
                            'high': float(parts[3]),
                            'low': float(parts[4]),
                            'volume': int(float(parts[5])),
                            'amount': float(parts[6]),
                            'amplitude': float(parts[7]),
                            'change_percent': float(parts[8]),
                            'change': float(parts[9]),
                            'turnover': float(parts[10])
                        })
                return {'code': code, 'klines': klines[-days:]}
            return {'code': code, 'klines': []}
        except Exception:
            return {'code': code, 'klines': []}

    def _get_kline_data_batch_primary(self, codes, days=20):
        kline_info = {}
        with ThreadPoolExecutor(max_workers=8) as executor:
            future_to_code = {executor.submit(self._get_kline_single, code, days): code for code in codes}
            for future in as_completed(future_to_code):
                result = future.result()
                kline_info[result['code']] = result['klines']
        return kline_info

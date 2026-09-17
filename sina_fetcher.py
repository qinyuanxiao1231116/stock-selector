import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

class SinaFetcher:
    """新浪财经备选数据源，当东方财富API失败时使用"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://finance.sina.com.cn'
        })
        self.timeout = 5

    def get_collection_bidding(self):
        """获取实时行情数据（新浪无集合竞价接口，用实时行情代替）"""
        try:
            # 先获取所有A股代码列表
            stock_list = self._get_stock_list()
            if not stock_list:
                return []

            # 批量获取实时行情（全量，每批800只）
            results = []
            batch_size = 800
            for i in range(0, len(stock_list), batch_size):
                batch = stock_list[i:i+batch_size]
                codes_str = ','.join(batch)
                url = f'https://hq.sinajs.cn/list={codes_str}'
                try:
                    resp = self.session.get(url, timeout=self.timeout)
                    lines = resp.text.strip().split('\n')
                    for line in lines:
                        try:
                            parts = line.split('="')
                            if len(parts) < 2:
                                continue
                            code_full = parts[0].split('_')[-1]
                            data = parts[1].rstrip('";')
                            fields = data.split(',')
                            if len(fields) < 32:
                                continue

                            name = fields[0]
                            open_price = float(fields[1]) if fields[1] else 0
                            prev_close = float(fields[2]) if fields[2] else 0
                            current_price = float(fields[3]) if fields[3] else 0
                            high = float(fields[4]) if fields[4] else 0
                            low = float(fields[5]) if fields[5] else 0
                            volume = int(float(fields[8])) if fields[8] else 0      # 成交量（股）
                            amount = float(fields[9]) if fields[9] else 0           # 成交额（元）
                            buy1_volume = int(float(fields[6])) if fields[6] else 0
                            sell1_volume = int(float(fields[18])) if fields[18] else 0

                            # 转换为东方财富 clist(fltt=2) 相同口径：
                            # f2=现价(元) f3=涨幅(%) f6=成交额(元) f18=昨收(元)
                            code_num = code_full[2:]
                            gain_pct = ((current_price - prev_close) / prev_close * 100
                                        if prev_close > 0 else 0)
                            results.append({
                                'f12': code_num,
                                'f14': name,
                                'f2': current_price,
                                'f3': round(gain_pct, 3),
                                'f6': amount,
                                'f15': high,
                                'f16': low,
                                'f17': open_price,
                                'f18': prev_close,
                                'f5': volume,
                                'f47': buy1_volume,
                                'f48': sell1_volume,
                            })
                        except (ValueError, IndexError):
                            continue

                    time.sleep(0.1)
                except Exception:
                    continue

            return results
        except Exception as e:
            print(f"新浪获取行情数据失败: {e}")
            return []

    def _get_stock_list(self):
        """获取沪深A股代码列表（分页拉取 sh_a + sz_a 两个节点，含主板与创业板）。
        注意：hs_a 节点现在混入北交所且首页只返回100只，不可直接使用。
        """
        codes = []
        url = 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData'
        for node in ('sh_a', 'sz_a'):
            page = 1
            while page <= 60:
                params = {
                    'page': page,
                    'num': 100,
                    'sort': 'symbol',
                    'asc': 1,
                    'node': node,
                    '_s_r_a': 'init'
                }
                try:
                    resp = self.session.get(url, params=params, timeout=self.timeout)
                    data = resp.json()
                    if not data:
                        break
                    for item in data:
                        symbol = item.get('symbol', '')
                        if symbol:
                            codes.append(symbol)
                    if len(data) < 100:
                        break
                    page += 1
                    time.sleep(0.15)
                except Exception:
                    break
        # 去重（sz_a 与 cyb 概念可能重叠）
        return list(dict.fromkeys(codes))

    def _get_stock_plate_single(self, code):
        """获取个股板块信息"""
        try:
            url = f'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData'
            params = {
                'page': 1,
                'num': 1,
                'sort': 'symbol',
                'asc': 1,
                'node': 'hs_a',
                'symbol': code,
                '_s_r_a': 'init'
            }
            resp = self.session.get(url, params=params, timeout=self.timeout)
            data = resp.json()
            if data:
                return {'code': code, 'industry': data[0].get('industry', ''), 'concept': '', 'region': '', 'market': ''}
            return {'code': code, 'industry': '', 'concept': '', 'region': '', 'market': ''}
        except Exception:
            return {'code': code, 'industry': '', 'concept': '', 'region': '', 'market': ''}

    def get_stock_plates_batch(self, codes):
        """批量获取板块信息"""
        plate_info = {}
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_code = {executor.submit(self._get_stock_plate_single, code): code for code in codes}
            for future in as_completed(future_to_code):
                result = future.result()
                plate_info[result['code']] = result
        return plate_info

    def _get_kline_single(self, code, days=7):
        """获取K线数据（日K）。
        旧域名 quotes.sina.cn/jsonp_v2 已失效（返回 null），
        使用 money.finance.sina.com.cn 的 JSON 接口。
        """
        try:
            sina_code = f'sh{code}' if code.startswith('6') else f'sz{code}'
            url = 'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData'
            params = {
                'symbol': sina_code,
                'scale': 240,      # 240分钟 = 日K
                'ma': 'no',
                'datalen': days + 5
            }
            resp = self.session.get(url, params=params, timeout=self.timeout)
            data = resp.json()
            klines = []
            for item in data:
                klines.append({
                    'date': item.get('day', ''),
                    'open': float(item.get('open', 0)),
                    'close': float(item.get('close', 0)),
                    'high': float(item.get('high', 0)),
                    'low': float(item.get('low', 0)),
                    'volume': int(float(item.get('volume', 0))),
                    'amount': 0,
                    'amplitude': 0,
                    'change_percent': 0,
                    'change': 0,
                    'turnover': 0
                })
            # 计算涨幅（新浪该接口不直接返回涨跌幅）
            for i in range(len(klines)):
                if i > 0 and klines[i-1]['close'] > 0:
                    klines[i]['change_percent'] = round(
                        (klines[i]['close'] - klines[i-1]['close']) / klines[i-1]['close'] * 100, 2
                    )
            return {'code': code, 'klines': klines}
        except Exception:
            return {'code': code, 'klines': []}

    def get_kline_data_batch(self, codes, days=20):
        """批量获取K线数据"""
        kline_info = {}
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_code = {executor.submit(self._get_kline_single, code, days): code for code in codes}
            for future in as_completed(future_to_code):
                result = future.result()
                kline_info[result['code']] = result['klines']
        return kline_info

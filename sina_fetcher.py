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

            # 批量获取实时行情
            results = []
            batch_size = 800
            for i in range(0, min(len(stock_list), 5000), batch_size):
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
                            buy1_volume = int(float(fields[6])) if fields[6] else 0
                            buy1_price = float(fields[7]) if fields[7] else 0
                            sell1_volume = int(float(fields[18])) if fields[18] else 0
                            sell1_price = float(fields[19]) if fields[19] else 0

                            # 转换为东方财富格式兼容
                            code_num = code_full[2:]
                            results.append({
                                'f12': code_num,
                                'f14': name,
                                'f2': int(current_price * 100) if current_price > 0 else '-',
                                'f3': int((current_price - prev_close) / prev_close * 10000) if prev_close > 0 else '-',
                                'f15': int(high * 100) if high > 0 else '-',
                                'f20': int(prev_close * 100) if prev_close > 0 else '-',
                                'f26': int(open_price * 100) if open_price > 0 else '-',
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
        """获取沪深A股代码列表"""
        try:
            url = 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData'
            params = {
                'page': 1,
                'num': 5000,
                'sort': 'symbol',
                'asc': 1,
                'node': 'hs_a',
                '_s_r_a': 'init'
            }
            resp = self.session.get(url, params=params, timeout=self.timeout)
            data = resp.json()
            codes = []
            for item in data:
                symbol = item.get('symbol', '')
                if symbol:
                    codes.append(symbol)
            return codes
        except Exception:
            # 如果获取列表失败，使用常见代码范围
            codes = []
            for i in range(600000, 602000):
                codes.append(f'sh{i}')
            for i in range(0, 2000):
                codes.append(f'sz{i:06d}')
            for i in range(300000, 301000):
                codes.append(f'sz{i}')
            return codes[:5000]

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
        """获取K线数据"""
        try:
            sina_code = f'sh{code}' if code.startswith('6') else f'sz{code}'
            url = f'https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_{sina_code}/CN_MarketDataService.getKLineData'
            params = {
                'symbol': sina_code,
                'scale': 1440,
                'ma': 'no',
                'datalen': days + 5
            }
            resp = self.session.get(url, params=params, timeout=self.timeout)
            text = resp.text
            # 解析JSONP
            json_str = text.split('(')[1].rstrip(')')
            import json
            data = json.loads(json_str)
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
            # 计算涨幅
            for i in range(len(klines)):
                if i > 0 and klines[i-1]['close'] > 0:
                    klines[i]['change_percent'] = round(
                        (klines[i]['close'] - klines[i-1]['close']) / klines[i-1]['close'] * 100, 2
                    )
            return {'code': code, 'klines': klines}
        except Exception:
            return {'code': code, 'klines': []}

    def get_kline_data_batch(self, codes, days=7):
        """批量获取K线数据"""
        kline_info = {}
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_code = {executor.submit(self._get_kline_single, code, days): code for code in codes}
            for future in as_completed(future_to_code):
                result = future.result()
                kline_info[result['code']] = result['klines']
        return kline_info

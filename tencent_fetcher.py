"""腾讯财经备选数据源（第三级降级）

数据源：
- 实时行情：https://qt.gtimg.cn/q=sh600519,sz000001
- 日K线：   https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh600519,day,...
- 股票列表：借用新浪 vip.stock.finance.sina.com.cn 的 sh_a/sz_a 节点（公开API，
            不依赖 sina_fetcher.py；腾讯本身的列表接口已失效）

字段口径与东方财富 fltt=2 保持一致：
- f2 现价(元)、f3 涨跌幅(%)、f6 成交额(元)、f18 昨收(元)
"""
import requests
import time
import datetime
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


class TencentFetcher:
    """腾讯财经备选数据源（第三级降级）"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://gu.qq.com'
        })
        self.timeout = 5

    # ---------- 实时行情 ----------
    def get_collection_bidding(self):
        """获取实时行情（腾讯无集合竞价接口，用实时行情代替）"""
        try:
            stock_list = self._get_stock_list()
            if not stock_list:
                logger.warning("[腾讯] 股票列表为空")
                return []

            results = []
            batch_size = 200  # 腾讯批量上限约200只
            for i in range(0, len(stock_list), batch_size):
                batch = stock_list[i:i + batch_size]
                codes_str = ','.join(batch)
                url = f'https://qt.gtimg.cn/q={codes_str}'
                try:
                    resp = self.session.get(url, timeout=self.timeout)
                    for line in resp.text.strip().split('\n'):
                        stock = self._parse_quote_line(line)
                        if stock:
                            results.append(stock)
                    time.sleep(0.1)
                except Exception as e:
                    logger.debug(f"[腾讯] 批量行情异常: {type(e).__name__}: {e}")
                    continue

            logger.info(f"[腾讯] 实时行情拉取完成: {len(results)}只")
            return results
        except Exception as e:
            logger.error(f"[腾讯] 获取行情失败: {type(e).__name__}: {e}")
            return []

    def _parse_quote_line(self, line):
        """解析腾讯单行行情数据
        格式：v_sh600519="1~贵州茅台~600519~1266.98~1258.00~...~价格/量/额~..."
        """
        try:
            if '="' not in line:
                return None
            code_part = line.split('=')[0]
            full_code = code_part.lstrip('v_')  # sh600519 / sz000001
            data_str = line.split('="')[1].rstrip('";')
            fields = data_str.split('~')
            if len(fields) < 36:
                return None

            code = full_code[2:]  # 去掉 sh/sz 前缀
            name = fields[1]
            current_price = float(fields[3]) if fields[3] else 0
            prev_close = float(fields[4]) if fields[4] else 0
            open_price = float(fields[5]) if fields[5] else 0
            volume_hand = float(fields[6]) if fields[6] else 0  # 手
            volume = int(volume_hand * 100)  # 股
            gain_pct = float(fields[32]) if fields[32] else 0  # %
            high = float(fields[33]) if fields[33] else 0
            low = float(fields[34]) if fields[34] else 0
            # fields[44]: 流通市值（亿元），需 ×1e8 转为元
            float_mv = float(fields[44]) * 1e8 if len(fields) > 44 and fields[44] else 0

            # 成交额：优先解析字段[35]的"价格/量/额"字符串（额为元）
            amount = 0.0
            if len(fields) > 35 and '/' in fields[35]:
                parts = fields[35].split('/')
                if len(parts) >= 3:
                    try:
                        amount = float(parts[2])
                    except ValueError:
                        amount = 0.0
            if amount == 0.0:
                # 退路：成交量(手)×100×均价 = 股×元 = 元
                avg = (high + low) / 2 if high > 0 and low > 0 else current_price
                amount = volume_hand * 100 * avg

            return {
                'f12': code,
                'f14': name,
                'f2': current_price,
                'f3': round(gain_pct, 3),
                'f6': amount,
                'f15': high,
                'f16': low,
                'f17': open_price,
                'f18': prev_close,
                'f5': volume,
                'f21': float_mv,   # 流通市值（元）
                # 兼容字段（东财用得到但腾讯不一定有）
                'f47': 0,   # buy1_volume
                'f48': 0,   # sell1_volume
            }
        except (ValueError, IndexError):
            return None

    # ---------- 股票列表（借用新浪公开API）----------
    def _get_stock_list(self):
        """获取沪深A股代码列表（sh_a + sz_a 节点，含主板与创业板）
        使用新浪 vip.stock.finance.sina.com.cn 的公开接口，独立实现，
        不依赖 sina_fetcher.py，避免新浪fetcher自身故障影响本类。
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
                        symbol = item.get('symbol', '')  # 形如 sh600519
                        if symbol:
                            codes.append(symbol)
                    if len(data) < 100:
                        break
                    page += 1
                    time.sleep(0.15)
                except Exception:
                    break
        return list(dict.fromkeys(codes))  # 去重保序

    # ---------- K线数据 ----------
    def _get_kline_single(self, code, days=20):
        """获取日K线（前复权）
        腾讯接口：web.ifzq.gtimg.cn/appstock/app/fqkline/get
        返回格式：data[code]['qfqday'] = [[日期, 开, 收, 高, 低, 量], ...]
        """
        try:
            sina_code = f'sh{code}' if code.startswith('6') else f'sz{code}'
            # 多取一些自然日以覆盖周末/节假日
            # 腾讯接口要求日期带横线分隔（YYYY-MM-DD）
            beg = (datetime.date.today() - datetime.timedelta(days=days * 2 + 20)).strftime('%Y-%m-%d')
            end = datetime.date.today().strftime('%Y-%m-%d')
            url = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
            params = {
                'param': f'{sina_code},day,{beg},{end},{days + 10},qfq'
            }
            resp = self.session.get(url, params=params, timeout=self.timeout)
            data = resp.json()
            klines = []
            if data.get('data') and data['data'].get(sina_code):
                stock_data = data['data'][sina_code]
                # qfqday = 前复权日K，day = 不复权日K
                day_list = stock_data.get('qfqday') or stock_data.get('day') or []
                for row in day_list:
                    if len(row) >= 6:
                        klines.append({
                            'date': row[0],
                            'open': float(row[1]),
                            'close': float(row[2]),
                            'high': float(row[3]),
                            'low': float(row[4]),
                            'volume': int(float(row[5])),
                            'amount': 0,
                            'amplitude': 0,
                            'change_percent': 0,
                            'change': 0,
                            'turnover': 0
                        })
                # 计算涨跌幅（腾讯K线接口不直接返回涨跌幅）
                for i in range(1, len(klines)):
                    if klines[i - 1]['close'] > 0:
                        klines[i]['change_percent'] = round(
                            (klines[i]['close'] - klines[i - 1]['close']) / klines[i - 1]['close'] * 100, 2
                        )
            return {'code': code, 'klines': klines[-days:] if len(klines) > days else klines}
        except Exception as e:
            logger.debug(f"[腾讯] K线获取失败 {code}: {type(e).__name__}: {e}")
            return {'code': code, 'klines': []}

    def get_kline_data_batch(self, codes, days=20):
        """批量获取K线数据"""
        kline_info = {}
        with ThreadPoolExecutor(max_workers=8) as executor:
            future_to_code = {executor.submit(self._get_kline_single, code, days): code for code in codes}
            for future in as_completed(future_to_code):
                result = future.result()
                kline_info[result['code']] = result['klines']
        return kline_info

    # ---------- 板块信息（暂不实现）----------
    def get_stock_plates_batch(self, codes):
        """板块信息暂不实现，返回空字典"""
        return {code: {'code': code, 'industry': '', 'concept': '', 'region': '', 'market': ''} for code in codes}

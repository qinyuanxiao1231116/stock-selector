import requests

class WechatNotifier:
    """Server酱推送（支持多人）"""

    def __init__(self, send_keys):
        if isinstance(send_keys, str):
            self.send_keys = [send_keys]
        else:
            self.send_keys = list(send_keys)
        self.base_url = 'https://sctapi.ftqq.com'

    def send_message(self, title, content):
        if not self.send_keys:
            print("[Server酱] 未配置SendKey，跳过推送")
            return False

        all_success = True
        for i, send_key in enumerate(self.send_keys):
            url = f'{self.base_url}/{send_key}.send'
            params = {
                'title': title,
                'desp': content
            }

            try:
                response = requests.post(url, data=params, timeout=10)
                result = response.json()

                if result.get('code') == 0:
                    print(f"[Server酱] 推送成功 (第{i+1}个人)")
                else:
                    print(f"[Server酱] 推送失败 (第{i+1}个人): {result.get('message', '未知错误')}")
                    all_success = False
            except Exception as e:
                print(f"[Server酱] 推送出错 (第{i+1}个人): {e}")
                all_success = False

        return all_success


class WxPusherNotifier:
    """WxPusher推送（免费不限条数，支持多人）"""

    def __init__(self, app_token, uids):
        self.app_token = app_token
        if isinstance(uids, str):
            self.uids = [uids]
        else:
            self.uids = list(uids)
        self.base_url = 'https://wxpusher.zjiecode.com/api/send/message'

    def send_message(self, title, content):
        if not self.app_token or not self.uids:
            print("[WxPusher] 未配置AppToken或UID，跳过推送")
            return False

        data = {
            'appToken': self.app_token,
            'content': f'## {title}\n\n{content}',
            'summary': title,
            'contentType': 2,  # 1=文本 2=html 3=markdown
            'uids': self.uids
        }

        try:
            response = requests.post(self.base_url, json=data, timeout=10)
            result = response.json()

            if result.get('code') == 1000:
                print(f"[WxPusher] 推送成功 ({len(self.uids)}人)")
                return True
            else:
                print(f"[WxPusher] 推送失败: {result.get('msg', '未知错误')}")
                return False
        except Exception as e:
            print(f"[WxPusher] 推送出错: {e}")
            return False


class MultiNotifier:
    """多通道推送，同时通过 Server酱 和 WxPusher 推送"""

    def __init__(self, notifiers):
        self.notifiers = [n for n in notifiers if n is not None]

    def send_message(self, title, content):
        if not self.notifiers:
            print("未配置任何推送通道，无法推送消息")
            return False

        all_success = True
        for notifier in self.notifiers:
            if not notifier.send_message(title, content):
                all_success = False
        return all_success

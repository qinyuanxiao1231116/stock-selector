import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import datetime
import threading
import time
import pandas as pd
from stock_filter import StockFilter
from config import (
    AUCTION_AMOUNT_THRESHOLD, AUCTION_GAIN_MIN, AUCTION_GAIN_MAX,
    AUCTION_GAIN_DIFF_THRESHOLD
)

class StockSelectorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("A股集合竞价选股系统")
        self.root.geometry("1200x800")
        self.root.resizable(True, True)

        self.filter = StockFilter()
        self.is_running = False
        self.update_thread = None
        self.snapshot_924 = None  # 9:24快照

        self.setup_styles()
        self.create_widgets()
        self.update_market_status()

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')

        style.configure('Title.TLabel', font=('Microsoft YaHei', 16, 'bold'), foreground='#2c3e50')
        style.configure('Status.TLabel', font=('Microsoft YaHei', 10), foreground='#7f8c8d')
        style.configure('Button.TButton', font=('Microsoft YaHei', 10), padding=6)
        style.configure('Header.TLabel', font=('Microsoft YaHei', 9, 'bold'), foreground='#34495e')

        style.map('Button.TButton',
                  background=[('active', '#3498db'), ('pressed', '#2980b9')],
                  foreground=[('active', 'white'), ('pressed', 'white')])

    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_frame = ttk.Frame(main_frame)
        title_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(title_frame, text="A股集合竞价选股系统", style='Title.TLabel').pack(side=tk.LEFT)

        status_frame = ttk.Frame(title_frame)
        status_frame.pack(side=tk.RIGHT)

        self.market_status_label = ttk.Label(status_frame, text="市场状态: ", style='Status.TLabel')
        self.market_status_label.pack(side=tk.LEFT, padx=10)

        self.market_status_value = ttk.Label(status_frame, text="休市", style='Status.TLabel')
        self.market_status_value.pack(side=tk.LEFT)

        self.time_label = ttk.Label(status_frame, text="", style='Status.TLabel')
        self.time_label.pack(side=tk.LEFT, padx=20)

        control_frame = ttk.Frame(main_frame)
        control_frame.pack(fill=tk.X, pady=(0, 10))

        self.btn_start = ttk.Button(control_frame, text="开始监控", command=self.start_monitoring, style='Button.TButton')
        self.btn_start.pack(side=tk.LEFT, padx=5)

        self.btn_stop = ttk.Button(control_frame, text="停止监控", command=self.stop_monitoring, style='Button.TButton', state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=5)

        self.btn_capture = ttk.Button(control_frame, text="采集9:24快照", command=self.capture_snapshot, style='Button.TButton')
        self.btn_capture.pack(side=tk.LEFT, padx=5)

        self.btn_refresh = ttk.Button(control_frame, text="手动刷新", command=self.refresh_data, style='Button.TButton')
        self.btn_refresh.pack(side=tk.LEFT, padx=5)

        self.btn_export = ttk.Button(control_frame, text="导出数据", command=self.export_data, style='Button.TButton')
        self.btn_export.pack(side=tk.LEFT, padx=5)

        settings_frame = ttk.LabelFrame(main_frame, text="早盘集合竞价选股条件", padding=10)
        settings_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(settings_frame, text="竞价金额阈值(万):").grid(row=0, column=0, sticky=tk.W, padx=10)
        self.amount_threshold = ttk.Entry(settings_frame, width=10)
        self.amount_threshold.insert(0, str(int(AUCTION_AMOUNT_THRESHOLD / 10000)))
        self.amount_threshold.grid(row=0, column=1, padx=5)

        ttk.Label(settings_frame, text="涨幅下限(%):").grid(row=0, column=2, sticky=tk.W, padx=10)
        self.gain_min = ttk.Entry(settings_frame, width=10)
        self.gain_min.insert(0, str(AUCTION_GAIN_MIN))
        self.gain_min.grid(row=0, column=3, padx=5)

        ttk.Label(settings_frame, text="涨幅上限(%):").grid(row=0, column=4, sticky=tk.W, padx=10)
        self.gain_max = ttk.Entry(settings_frame, width=10)
        self.gain_max.insert(0, str(AUCTION_GAIN_MAX))
        self.gain_max.grid(row=0, column=5, padx=5)

        ttk.Label(settings_frame, text="9:25较9:24拉升(%):").grid(row=0, column=6, sticky=tk.W, padx=10)
        self.gain_diff_threshold = ttk.Entry(settings_frame, width=10)
        self.gain_diff_threshold.insert(0, str(AUCTION_GAIN_DIFF_THRESHOLD))
        self.gain_diff_threshold.grid(row=0, column=7, padx=5)

        self.snapshot_status = ttk.Label(settings_frame, text="快照状态: 未采集", style='Status.TLabel')
        self.snapshot_status.grid(row=1, column=0, columnspan=8, sticky=tk.W, padx=10, pady=(5, 0))

        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True)

        self.auction_frame = ttk.Frame(notebook)
        notebook.add(self.auction_frame, text="集合竞价选股")

        self.create_tree(self.auction_frame, 'auction')

        self.results = {
            'auction': [],
        }

    def create_tree(self, parent, tree_type):
        columns = ('code', 'name', 'price', 'prev_close', 'gain', 'gain_924', 'gain_diff', 'amount', 'industry', 'concept')

        tree = ttk.Treeview(parent, columns=columns, show='headings', selectmode='browse')

        tree.heading('code', text='代码')
        tree.heading('name', text='名称')
        tree.heading('price', text='竞价价')
        tree.heading('prev_close', text='昨收')
        tree.heading('gain', text='涨幅(%)')
        tree.heading('gain_924', text='9:24涨幅(%)')
        tree.heading('gain_diff', text='拉升(%)')
        tree.heading('amount', text='竞价金额(万)')
        tree.heading('industry', text='行业')
        tree.heading('concept', text='概念')

        tree.column('code', width=80)
        tree.column('name', width=100)
        tree.column('price', width=80, anchor=tk.RIGHT)
        tree.column('prev_close', width=80, anchor=tk.RIGHT)
        tree.column('gain', width=80, anchor=tk.RIGHT)
        tree.column('gain_924', width=100, anchor=tk.RIGHT)
        tree.column('gain_diff', width=80, anchor=tk.RIGHT)
        tree.column('amount', width=100, anchor=tk.RIGHT)
        tree.column('industry', width=120)
        tree.column('concept', width=150)

        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)

        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        setattr(self, f'{tree_type}_tree', tree)

    def update_market_status(self):
        status = self.filter.get_market_status()
        status_text = {
            'before_market': '未开盘',
            'collection_bidding_1': '集合竞价(9:15-9:20)',
            'collection_bidding_2': '集合竞价(9:20-9:25)',
            'continuous_trading_morning': '连续竞价(上午)',
            'lunch_break': '午休',
            'continuous_trading_afternoon': '连续竞价(下午)',
            'auction_trading_afternoon': '尾盘竞价',
            'after_market': '已收盘'
        }
        self.market_status_value.config(text=status_text.get(status, '休市'))

        now = datetime.datetime.now()
        self.time_label.config(text=now.strftime('%Y-%m-%d %H:%M:%S'))

        self.root.after(1000, self.update_market_status)

    def start_monitoring(self):
        self.is_running = True
        self.btn_start.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)

        self.update_thread = threading.Thread(target=self.monitor_loop, daemon=True)
        self.update_thread.start()

    def stop_monitoring(self):
        self.is_running = False
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)

    def monitor_loop(self):
        while self.is_running:
            try:
                self.refresh_data()
                time.sleep(5)
            except Exception as e:
                print(f"监控循环出错: {e}")
                break

    def capture_snapshot(self):
        """采集当前行情作为9:24快照"""
        try:
            self.snapshot_924 = self.filter.fetcher.get_collection_bidding()
            count = len(self.snapshot_924) if self.snapshot_924 else 0
            self.snapshot_status.config(text=f"快照状态: 已采集 ({count}只) - {datetime.datetime.now().strftime('%H:%M:%S')}")
            messagebox.showinfo("成功", f"9:24快照采集完成，共 {count} 只股票")
        except Exception as e:
            messagebox.showerror("错误", f"采集快照失败: {str(e)}")

    def refresh_data(self):
        try:
            amount_threshold = float(self.amount_threshold.get()) * 10000  # 万 -> 元
            gain_min = float(self.gain_min.get())
            gain_max = float(self.gain_max.get())
            gain_diff_threshold = float(self.gain_diff_threshold.get())

            auction_stocks = self.filter.filter_auction_momentum(
                snapshot_924=self.snapshot_924,
                amount_threshold=amount_threshold,
                gain_min=gain_min,
                gain_max=gain_max,
                gain_diff_threshold=gain_diff_threshold
            )

            self.results['auction'] = auction_stocks
            self.update_tree('auction', auction_stocks)

        except Exception as e:
            messagebox.showerror("错误", f"刷新数据失败: {str(e)}")

    def update_tree(self, tree_type, data):
        tree = getattr(self, f'{tree_type}_tree')

        for item in tree.get_children():
            tree.delete(item)

        for item in data:
            values = (
                item['code'],
                item['name'],
                item['price'],
                item['prev_close'],
                item['gain'],
                item.get('gain_924') if item.get('gain_924') is not None else '-',
                item.get('gain_diff') if item.get('gain_diff') is not None else '-',
                item['amount'],
                item['industry'],
                item['concept']
            )
            tree.insert('', tk.END, values=values)

    def export_data(self):
        file_path = filedialog.asksaveasfilename(
            defaultextension='.xlsx',
            filetypes=[('Excel文件', '*.xlsx'), ('CSV文件', '*.csv')],
            title='导出选股结果'
        )

        if not file_path:
            return

        try:
            writer = pd.ExcelWriter(file_path, engine='openpyxl')

            if self.results['auction']:
                df_auction = pd.DataFrame(self.results['auction'])
                df_auction.to_excel(writer, sheet_name='集合竞价选股', index=False)

            writer.close()
            messagebox.showinfo("成功", f"数据已导出到: {file_path}")
        except Exception as e:
            messagebox.showerror("错误", f"导出失败: {str(e)}")

def main():
    root = tk.Tk()
    app = StockSelectorGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()

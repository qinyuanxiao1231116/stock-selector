import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import datetime
import threading
import time
import pandas as pd
from stock_filter import StockFilter

class StockSelectorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("A股集合竞价选股系统")
        self.root.geometry("1200x800")
        self.root.resizable(True, True)
        
        self.filter = StockFilter()
        self.is_running = False
        self.update_thread = None
        
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
        
        self.btn_refresh = ttk.Button(control_frame, text="手动刷新", command=self.refresh_data, style='Button.TButton')
        self.btn_refresh.pack(side=tk.LEFT, padx=5)
        
        self.btn_export = ttk.Button(control_frame, text="导出数据", command=self.export_data, style='Button.TButton')
        self.btn_export.pack(side=tk.LEFT, padx=5)
        
        settings_frame = ttk.LabelFrame(main_frame, text="筛选参数设置", padding=10)
        settings_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(settings_frame, text="涨停封单阈值(手):").grid(row=0, column=0, sticky=tk.W, padx=10)
        self.limit_up_threshold = ttk.Entry(settings_frame, width=10)
        self.limit_up_threshold.insert(0, "10000")
        self.limit_up_threshold.grid(row=0, column=1, padx=5)
        
        ttk.Label(settings_frame, text="跳空高开阈值(%):").grid(row=0, column=2, sticky=tk.W, padx=10)
        self.gap_threshold = ttk.Entry(settings_frame, width=10)
        self.gap_threshold.insert(0, "1.0")
        self.gap_threshold.grid(row=0, column=3, padx=5)
        
        ttk.Label(settings_frame, text="抢筹成交量阈值(手):").grid(row=0, column=4, sticky=tk.W, padx=10)
        self.buy_volume_threshold = ttk.Entry(settings_frame, width=10)
        self.buy_volume_threshold.insert(0, "5000")
        self.buy_volume_threshold.grid(row=0, column=5, padx=5)
        
        ttk.Label(settings_frame, text="抢筹涨幅阈值(%):").grid(row=0, column=6, sticky=tk.W, padx=10)
        self.buy_price_threshold = ttk.Entry(settings_frame, width=10)
        self.buy_price_threshold.insert(0, "2.0")
        self.buy_price_threshold.grid(row=0, column=7, padx=5)
        
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True)
        
        self.limit_up_frame = ttk.Frame(notebook)
        notebook.add(self.limit_up_frame, text="涨停封单加大")
        
        self.gapping_up_frame = ttk.Frame(notebook)
        notebook.add(self.gapping_up_frame, text="跳空高开")
        
        self.buying_rush_frame = ttk.Frame(notebook)
        notebook.add(self.buying_rush_frame, text="抢筹动作")
        
        self.create_tree(self.limit_up_frame, 'limit_up')
        self.create_tree(self.gapping_up_frame, 'gapping_up')
        self.create_tree(self.buying_rush_frame, 'buying_rush')
        
        self.results = {
            'limit_up': [],
            'gapping_up': [],
            'buying_rush': []
        }
    
    def create_tree(self, parent, tree_type):
        columns = []
        if tree_type == 'limit_up':
            columns = ('code', 'name', 'price', 'limit_up', 'buy1', 'change', 'industry', 'concept')
        elif tree_type == 'gapping_up':
            columns = ('code', 'name', 'current', 'prev_close', 'open', 'gap', 'industry', 'concept')
        elif tree_type == 'buying_rush':
            columns = ('code', 'name', 'current', 'prev_close', 'increase', 'buy1', 'sell1', 'ratio', 'industry', 'concept')
        
        tree = ttk.Treeview(parent, columns=columns, show='headings', selectmode='browse')
        
        if tree_type == 'limit_up':
            tree.heading('code', text='代码')
            tree.heading('name', text='名称')
            tree.heading('price', text='当前价')
            tree.heading('limit_up', text='涨停价')
            tree.heading('buy1', text='涨停封单(手)')
            tree.heading('change', text='涨幅(%)')
            tree.heading('industry', text='行业')
            tree.heading('concept', text='概念')
            
            tree.column('code', width=80)
            tree.column('name', width=100)
            tree.column('price', width=80, anchor=tk.RIGHT)
            tree.column('limit_up', width=80, anchor=tk.RIGHT)
            tree.column('buy1', width=100, anchor=tk.RIGHT)
            tree.column('change', width=80, anchor=tk.RIGHT)
            tree.column('industry', width=120)
            tree.column('concept', width=150)
            
        elif tree_type == 'gapping_up':
            tree.heading('code', text='代码')
            tree.heading('name', text='名称')
            tree.heading('current', text='当前价')
            tree.heading('prev_close', text='昨收')
            tree.heading('open', text='开盘价')
            tree.heading('gap', text='跳空幅度(%)')
            tree.heading('industry', text='行业')
            tree.heading('concept', text='概念')
            
            tree.column('code', width=80)
            tree.column('name', width=100)
            tree.column('current', width=80, anchor=tk.RIGHT)
            tree.column('prev_close', width=80, anchor=tk.RIGHT)
            tree.column('open', width=80, anchor=tk.RIGHT)
            tree.column('gap', width=100, anchor=tk.RIGHT)
            tree.column('industry', width=120)
            tree.column('concept', width=150)
            
        elif tree_type == 'buying_rush':
            tree.heading('code', text='代码')
            tree.heading('name', text='名称')
            tree.heading('current', text='当前价')
            tree.heading('prev_close', text='昨收')
            tree.heading('increase', text='涨幅(%)')
            tree.heading('buy1', text='买一量(手)')
            tree.heading('sell1', text='卖一量(手)')
            tree.heading('ratio', text='买卖比')
            tree.heading('industry', text='行业')
            tree.heading('concept', text='概念')
            
            tree.column('code', width=80)
            tree.column('name', width=100)
            tree.column('current', width=80, anchor=tk.RIGHT)
            tree.column('prev_close', width=80, anchor=tk.RIGHT)
            tree.column('increase', width=80, anchor=tk.RIGHT)
            tree.column('buy1', width=80, anchor=tk.RIGHT)
            tree.column('sell1', width=80, anchor=tk.RIGHT)
            tree.column('ratio', width=80, anchor=tk.RIGHT)
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
    
    def refresh_data(self):
        try:
            limit_up_threshold = int(self.limit_up_threshold.get())
            gap_threshold = float(self.gap_threshold.get())
            buy_volume_threshold = int(self.buy_volume_threshold.get())
            buy_price_threshold = float(self.buy_price_threshold.get())
            
            limit_up_stocks = self.filter.filter_limit_up_with_increasing_bids(limit_up_threshold)
            gapping_up_stocks = self.filter.filter_gapping_up(gap_threshold)
            buying_rush_stocks = self.filter.filter_buying_rush(buy_volume_threshold, buy_price_threshold)
            
            self.results['limit_up'] = limit_up_stocks
            self.results['gapping_up'] = gapping_up_stocks
            self.results['buying_rush'] = buying_rush_stocks
            
            self.update_tree('limit_up', limit_up_stocks)
            self.update_tree('gapping_up', gapping_up_stocks)
            self.update_tree('buying_rush', buying_rush_stocks)
            
        except Exception as e:
            messagebox.showerror("错误", f"刷新数据失败: {str(e)}")
    
    def update_tree(self, tree_type, data):
        tree = getattr(self, f'{tree_type}_tree')
        
        for item in tree.get_children():
            tree.delete(item)
        
        for item in data:
            if tree_type == 'limit_up':
                values = (
                    item['code'],
                    item['name'],
                    item['price'],
                    item['limit_up_price'],
                    item['buy1_volume'],
                    item['change_percent'],
                    item['industry'],
                    item['concept']
                )
            elif tree_type == 'gapping_up':
                values = (
                    item['code'],
                    item['name'],
                    item['current_price'],
                    item['prev_close'],
                    item['open_price'],
                    item['gap_percent'],
                    item['industry'],
                    item['concept']
                )
            elif tree_type == 'buying_rush':
                values = (
                    item['code'],
                    item['name'],
                    item['current_price'],
                    item['prev_close'],
                    item['price_increase'],
                    item['buy1_volume'],
                    item['sell1_volume'],
                    item['buy_sell_ratio'],
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
            
            if self.results['limit_up']:
                df_limit_up = pd.DataFrame(self.results['limit_up'])
                df_limit_up.to_excel(writer, sheet_name='涨停封单加大', index=False)
            
            if self.results['gapping_up']:
                df_gapping_up = pd.DataFrame(self.results['gapping_up'])
                df_gapping_up.to_excel(writer, sheet_name='跳空高开', index=False)
            
            if self.results['buying_rush']:
                df_buying_rush = pd.DataFrame(self.results['buying_rush'])
                df_buying_rush.to_excel(writer, sheet_name='抢筹动作', index=False)
            
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
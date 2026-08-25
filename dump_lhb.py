from backend.data_collector import DataCollector
import pandas as pd

df = DataCollector.fetch_lhb_data('20260707')
if df is not None and not df.empty:
    cols = ['代码', '名称', '收盘价', '涨跌幅', '机构买入净额', '流通市值', '上榜原因']
    df = df[[c for c in cols if c in df.columns]]
    if '机构买入净额' in df.columns:
        df['机构买入净额(万)'] = (df['机构买入净额'] / 10000).round(2)
    else:
        df['机构买入净额(万)'] = 0
        
    if '流通市值' in df.columns:
        df['流通市值(亿)'] = (df['流通市值'] / 100000000).round(2)
    else:
        df['流通市值(亿)'] = 0
        
    if '机构买入净额' in df.columns:
        df = df.drop(columns=['机构买入净额'])
    if '流通市值' in df.columns:
        df = df.drop(columns=['流通市值'])
        
    md_str = df.to_markdown(index=False)
    with open('output/lhb_raw_20260707.md', 'w', encoding='utf-8') as f:
        f.write(md_str)
    print("SUCCESS")
else:
    print("NO DATA")

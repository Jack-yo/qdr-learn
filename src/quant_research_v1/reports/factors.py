"""Portable HTML report with native SVG diagnostics, no network assets."""
import html
import json
import math

import pandas as pd


def decay_svg(rows):
    colors = {"train":"#2563eb","validation":"#d97706"}
    content = ['<svg viewBox="0 0 480 180" width="480" role="img" aria-label="Mean Rank IC at horizons 1, 3, 5">',
               '<path d="M40 90H450" stroke="#aaa"/><text x="4" y="94" font-size="11">0</text>']
    values = [abs(v) for v in rows.rank_ic_mean if pd.notna(v)]
    scale = max([0.05]+values)
    for partition,color in colors.items():
        points = []
        for _,row in rows.loc[rows.partition.eq(partition)].iterrows():
            x = {1:90,3:245,5:400}[row.horizon]
            if pd.notna(row.rank_ic_mean):
                y = 90-float(row.rank_ic_mean)/scale*65
                points.append(f"{x},{y:.2f}")
                content.append(f'<circle cx="{x}" cy="{y:.2f}" r="4" fill="{color}"><title>{partition} H{row.horizon}: {row.rank_ic_mean:.6f}</title></circle>')
        if points:
            content.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}"/>')
    for horizon,x in [(1,90),(3,245),(5,400)]:
        content.append(f'<text x="{x-10}" y="175" font-size="12">H{horizon}</text>')
    content.append('</svg><p>蓝：训练；橙：验证。纵轴范围 ±'+f'{scale:.4f}'+'；缺失值无标记。</p>')
    return "".join(content)


def render_report(destination, manifest, results):
    summary = results["summary"]
    blocks = []
    for name,rows in summary.groupby("factor",sort=False):
        columns = ["partition","horizon","rank_ic_mean","icir_unannualized","ic_mean_ci95_low","ic_mean_ci95_high","feature_coverage","daily_ic_count"]
        groups = ["partition","horizon"]+[f"q{i}_mean_forward_price_return" for i in range(1,6)]
        blocks.append('<section><h2>'+html.escape(name)+'</h2>'+decay_svg(rows)+
                      rows[columns].to_html(index=False,na_rep="缺失",float_format=lambda x:f"{x:.6f}")+ 
                      '<details><summary>五分组未来价格收益（未计成本）</summary>'+rows[groups].to_html(index=False,na_rep="缺失",float_format=lambda x:f"{x:.6f}")+'</details></section>')
    payload = html.escape(json.dumps(manifest,indent=2,ensure_ascii=False))
    text = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>P2 因子工程研究报告</title>
<style>body{font:15px system-ui;margin:32px;max-width:1300px;color:#172033}h1{font-size:28px}.notice{padding:18px;background:#fff4df;border-left:5px solid #d97706}table{border-collapse:collapse;font-size:12px;display:block;overflow:auto}td,th{padding:7px;border:1px solid #ddd}section{margin-top:32px;border-top:1px solid #ddd}pre{white-space:pre-wrap}svg{max-width:100%}</style>
<h1>P2 因子工程研究报告</h1><div class="notice"><strong>EXPLORATORY / NOT_READY — 不构成股票 Alpha 或策略盈利证据</strong><p>使用所选真实来源的当前版本 ETF 代理面板。Yahoo 为 split-adjusted OHLC 价格代理，不是历史原始价成交收益；所有历史决策资格与成本后收益均未获证实。2025 年起最终策略测试期封存。</p></div>
<p>每日横截面 Spearman Rank IC；ICIR=日 IC 均值/样本标准差，不年化。95% 区间为固定 20 交易日循环块 bootstrap，保留时间依赖；不提供逐日 iid p 值或多重检验后的 Alpha 声明。分组统计和条件结果为描述性统计。</p>
<p>行业、市值暴露缺少 PIT 输入；风格相关性等待 P3。未用最新财报或当前市值回填。换手仅指最高分组成员等权变动，不是实际组合交易。</p>'''
    text += f"<p>训练期末另保留 {manifest['experiment']['embargo_sessions']} 个交易日 gap，并剔除退出跨分区边界的标签；最终测试期未参与统计。</p>"
    text += "".join(blocks)
    text = text.replace("固定 20 交易日循环块 bootstrap",f"固定 {manifest['experiment']['bootstrap_block_sessions']} 交易日循环块 bootstrap（{manifest['experiment']['bootstrap_replicates']} 次）")
    text += '<h2>因子相关性</h2>'+results["factor_correlations"].to_html(index=False,na_rep="缺失")
    text += '<h2>市场条件：SPY 过去 20 日价格收益正/非正</h2>'+results["conditional_ic"].to_html(index=False,na_rep="缺失")
    text += '<details><summary>数据来源、冻结参数与运行元信息</summary><pre>'+payload+'</pre></details></html>'
    (destination/"report.html").write_text(text,encoding="utf-8")

# A 股上升周期筛选器 v1.2

v1.2 把“下载行情”和“筛选股票”分开：行情先写入 SQLite，五项技术条件和
全市场 60 日收益百分位随后完全在本地计算。

## 目录结构

```text
a_share_screener/
├── app/                  程序代码
│   ├── market_db.py
│   ├── update_market.py
│   ├── screener_v1_1.py
│   ├── screener_v1_2.py
│   └── run_daily.py
├── data/                 SQLite 行情数据库
├── output/               JSON、CSV 筛选结果
├── README.md             使用说明
└── requirements.txt      Python 依赖
```

默认数据库位置为 `data/market.db`，默认结果目录为 `output/`。

## 1. 安装依赖

在项目虚拟环境中执行：

```powershell
python -m pip install -r requirements.txt
```

## 2. 设置 Tushare Token

可以复制项目提供的模板，再编辑 `.env`：

```bash
cp .env.example .env
```

文件内容为：

```dotenv
TUSHARE_TOKEN=你的Tushare Token
```

Linux服务器可以限制该文件只能由当前用户读取：

```bash
chmod 600 .env
```

程序读取顺序为：

1. 当前进程的 `TUSHARE_TOKEN` 环境变量。
2. 项目根目录的 `.env` 文件。

也可以不创建文件，直接在当前终端临时设置。Windows PowerShell：

```powershell
$env:TUSHARE_TOKEN="你的 Tushare Token"
```

Linux或macOS：

```bash
export TUSHARE_TOKEN="你的 Tushare Token"
```

`.env` 已被 `.gitignore` 排除，不会加入Git提交。程序不会把Token写入源码或
数据库。初始化前请确认账号具有 `daily` 和 `adj_factor` 的调用权限。

## 3. 第一次初始化

```powershell
python app/update_market.py --init --days 250
```

程序按照沪深300的交易日期，逐日批量下载全市场行情。每个交易日单独提交，
所以中断后重新执行同一命令即可继续，不会重复插入数据。

查看进度和数据库状态：

```powershell
python app/update_market.py --status
```

如果某一天失败，错误会记录在数据库中。重新执行初始化命令会继续补齐。

## 4. 本地扫描

全市场扫描：

```powershell
python app/screener_v1_2.py --all
```

小样本检查：

```powershell
python app/screener_v1_2.py --symbols 603505 600519 000858
```

小样本模式不会用三只股票之间的排名冒充全市场百分位。该字段为 `N/A`，也不
参与相对强度条件。

## 5. 每日运行

完成首次初始化后，每个交易日收盘数据更新完毕再执行：

```powershell
python app/run_daily.py
```

它等价于：

```powershell
python app/update_market.py --daily
python app/screener_v1_2.py --all
```

如果行情更新不完整，一键入口会停止，不会覆盖上一份有效筛选结果。

## 数据与复权

数据库保存 Tushare 未复权价格和每日复权因子。筛选时按每只股票最新因子动态
生成前复权 OHLC：

```text
前复权价格 = 原始价格 × 当日复权因子 ÷ 最新复权因子
```

这样分红除权发生后不需要改写整段历史价格。成交量保持原始“手”数，不复权。

沪深300行情来自 AKShare 腾讯指数接口；股票名称来自
`stock_info_a_code_name()`。

## 输出

继续生成与 v1.1 相同的文件：

```text
output/
├── candidates.json
├── candidates.csv
├── technical_pass_5of5.json
├── watchlist_4of5.json
└── errors.csv
```

## 常用维护命令

强制重取最近 5 个交易日：

```powershell
python app/update_market.py --daily --repair-days 5
```

扫描过去某个历史截面：

```powershell
python app/screener_v1_2.py --all --end-date 20260911
```

数据库初始化不足 120 个交易日时，部分股票会因为历史长度不足进入
`errors.csv`；建议初始化 250 个交易日。

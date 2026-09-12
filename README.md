# A 股上升周期筛选器 v1.2

v1.2 把“下载行情”和“筛选股票”分开：行情先写入 SQLite，五项技术条件和
全市场 60 日收益百分位随后完全在本地计算。

## 目录结构

```text
a_share_screener/
├── app/                  程序代码
│   ├── market_db.py
│   ├── update_market.py
│   ├── providers/          可替换的数据源适配器
│   │   └── tencent.py
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

## 2. 选择数据源

初始化时必须选择一种个股数据源：

| 选择 | 行情方式 | 适合用户 |
|---|---|---|
| `--tx` | 腾讯直接提供沪深股票前复权日线 | 没有Tushare Token、复权因子只有试用低频权限，或者希望完全免费运行的用户 |
| `--tushare` | Tushare未复权日线＋复权因子，本地动态计算前复权 | 已具备 `daily` 和 `adj_factor` 正式权限、需要包含北交所，而且复权因子调用频率足以完成初始化的用户 |

之所以必须明确选择，是因为两个平台的复权算法、价格精度和更新时间可能存在
差异。一个数据库只能使用一种个股数据源，不能把腾讯和Tushare的价格按日期
拼接，否则均线和收益率可能在数据源切换处出现假跳空。

数据源选择会写入SQLite数据库。以后执行 `--daily` 时程序自动读取初始化选择，
用户不能临时切换数据源。如果需要换源，必须指定新的数据库文件重新初始化。

### 腾讯用户

腾讯模式不需要Token，可以直接跳到“第一次初始化”。腾讯按股票下载完整的
前复权窗口，网络请求数量较多，但支持并发、按股票保存和断点续传，适合放在
Ubuntu服务器后台运行。当前腾讯历史接口只可靠支持沪深股票，北交所股票会被
明确跳过，因此腾讯模式的“全市场百分位”实际指沪深市场。需要沪深京完整覆盖
时应选择Tushare模式。

### Tushare用户

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
数据库。选择Tushare初始化前，请确认账号具有 `daily` 和 `adj_factor` 的正式
调用权限。若服务端提示 `adj_factor` 只有每小时1次，初始化250个交易日约需
10天，不建议选择Tushare，应改用腾讯模式。

## 3. 第一次初始化

腾讯前复权模式（没有Tushare高频复权因子权限时推荐）：

```powershell
python app/update_market.py --init --tx --days 250
```

Tushare模式：

```powershell
python app/update_market.py --init --tushare --days 250
```

腾讯模式按股票提交，Tushare模式按交易日提交。两种模式都支持断点续传，按
`Ctrl+C` 中断后重新执行原初始化命令即可继续。

腾讯默认同时下载6只股票，可以按服务器和网络情况调整：

```powershell
python app/update_market.py --init --tx --days 250 --tx-workers 8
```

`--tx-workers` 表示腾讯并发请求数，不建议盲目调得很高，以免触发远端限制。

Tushare更新器默认按 `daily` 每分钟50次、`adj_factor` 每分钟1次分别限速。
如果账号具有更高的复权因子权限，例如每分钟200次，可以明确提高限制：

```powershell
python app/update_market.py --init --tushare --days 250 --adj-factor-per-minute 200
```

`--adj-factor-per-minute` 必须与账号实际权限一致。程序如果收到“频率超限”错误，
会读取服务端返回的每分钟或每小时限制，自动降低速度并等待，不再进行几秒钟
内的无效重试。

查看进度和数据库状态：

```powershell
python app/update_market.py --status
```

腾讯失败股票或Tushare失败日期都会记录在数据库中；重新执行原初始化命令会
继续补齐。

如果当前数据库已经使用Tushare初始化，但希望改用腾讯，请使用一个新的数据
库文件，避免混合两个来源：

```powershell
python app/update_market.py --init --tx --days 250 --db data/market_tx.db
python app/screener_v1_2.py --all --db data/market_tx.db
python app/run_daily.py --db data/market_tx.db
```

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

每日入口会从数据库读取初始化数据源：腾讯数据库继续使用腾讯，Tushare数据库
继续使用Tushare。日常更新命令不接受 `--tx` 或 `--tushare`，防止误切数据源。

它等价于：

```powershell
python app/update_market.py --daily
python app/screener_v1_2.py --all
```

如果行情更新不完整，一键入口会停止，不会覆盖上一份有效筛选结果。

## 数据与复权

Tushare模式保存未复权价格和每日复权因子，筛选时按每只股票最新因子动态生成
前复权OHLC：

```text
前复权价格 = 原始价格 × 当日复权因子 ÷ 最新复权因子
```

这样分红除权发生后不需要改写整段历史价格。成交量保持原始“手”数，不复权。

腾讯模式直接保存腾讯已经计算完成的前复权OHLC。因为前复权历史会在新的分红
除权发生后变化，腾讯的日常更新会重新获取并覆盖每只股票最近 `--days` 个交易
日，而不是只追加当天一行。

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

在腾讯模式中，前复权是完整动态序列，因此该命令会重新下载所有股票的完整
窗口；在Tushare模式中只强制重取最近5个交易日。

扫描过去某个历史截面：

```powershell
python app/screener_v1_2.py --all --end-date 20260911
```

数据库初始化不足 120 个交易日时，部分股票会因为历史长度不足进入
`errors.csv`；建议初始化 250 个交易日。

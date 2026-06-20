# AI Quant Agent

LLM 驱动的量化交易 Agent — 集成市场数据、技术分析、情绪评分、回测和自动交易。

## 项目结构

```
ai_quant_agent/
├── main.py                  # 主入口
├── config.py                # 配置加载 (.env)
├── scheduler.py             # 定时调度器
├── connectors/              # 数据连接器
│   ├── binance_rest.py      # Binance REST API
│   ├── coingecko.py         # CoinGecko 行情
│   ├── news_source.py       # 新闻源
│   └── x_watchlist.py       # X/Twitter 监控
├── backtest/                # 回测引擎
│   ├── engine.py            # 向量化回测
│   ├── metrics.py           # 绩效指标
│   └── anti_lookahead.py    # 前视偏差检查
├── analysis/                # 分析模块
│   ├── indicators.py        # 技术指标 (RSI, MACD, BB, ATR...)
│   ├── event_scoring.py     # 事件评分
│   ├── sentiment_scoring.py # 情感评分
│   └── decision_schema.py   # 决策数据结构
├── llm/                     # LLM 决策
│   ├── prompts.py           # Prompt 模板
│   ├── main_decision_agent.py # 主决策 Agent
│   └── validator_agent.py   # 验证 Agent
├── risk/                    # 风控
│   ├── risk_control.py      # 风控规则
│   ├── truth_check.py       # 数据完整性检查
│   └── position_sizing.py   # 仓位管理 (Kelly, ATR)
├── execution/               # 执行
│   ├── paper_trade.py       # 模拟交易
│   ├── binance_testnet.py   # Binance 测试网
│   └── kill_switch.py       # 紧急停止
├── reports/                 # 报告
│   ├── daily_report.py      # 日报生成
│   └── templates/           # 报告模板
├── data/                    # 数据目录
│   ├── raw/                 # 原始数据
│   ├── processed/           # 处理数据
│   └── backtest/            # 回测结果
└── logs/                    # 日志
```

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API Key

# 运行一次决策
python main.py --once --symbol BTCUSDT

# 运行回测
python main.py --backtest --symbol BTCUSDT

# 守护模式
python main.py --daemon
```

## 工作流程

1. **数据采集** — Binance/CoinGecko/新闻/Twitter
2. **技术分析** — 指标计算 + 事件评分
3. **LLM 决策** — GPT-4 或 DeepSeek 分析市场并给出交易建议
4. **验证** — Validator Agent 交叉检查
5. **风控** — 仓位限制、每日亏损上限、杀开关
6. **执行** — 模拟交易或 Binance 测试网

> ⚠️ 仅用于教育和研究目的。使用实时交易需自行承担风险。

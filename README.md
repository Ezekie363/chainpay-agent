# ChainQuery Agent

**AI × Web3 hackathon — Cobo 赛道 01：Agent-Native Payments**

一个能自主为链上数据查询付费的 AI Agent，支付通过 x402 协议完成，由 Cobo MPC Agentic Wallet 签名执行。

---

## 项目简介

ChainQuery Agent 展示了完整的 **AI 原生支付闭环**：用户提出区块链数据问题，Agent 自动调用付费 API，通过 x402 协议签名并提交 $0.01 USDC 微支付，最终返回真实链上数据——全程无需人工审批任何支付。

**交互示例：**

```
You: BTC 和 ETH 的价格分别是多少？顺便查一下 gas

  ✔ Token Price  (19,428 ms)  −$0.01 USDC  ETH = $1,571.87
  ✔ Token Price  (19,479 ms)  −$0.01 USDC  BTC = $61,077.00
  ✔ Gas Price    (19,561 ms)  −$0.01 USDC  0.01 gwei

Agent: ETH 当前价格 $1,571.87，BTC $61,077。Base Sepolia gas 极低（0.01 gwei）。
       本次共支付 0.03 USDC。
```

USDC 扣款真实发生在 Base Sepolia 上，可在链上查验。

---

## 系统架构

```
用户 CLI
   │
   ▼
DeepSeek LLM（工具调用）
   │  决定需要哪些链上查询
   ▼
chain_query.py  ──[x402 自动付费]──►  ChainData API 服务端
   │                                          │
   │  CawSigner（EIP-712 MPC 签名）           │  x402 中间件
   │        │                                 │
   ▼        ▼                                 ▼
Cobo Agentic Wallet ──[USDC]──► x402 Facilitator（x402.org）
（Base Sepolia MPC）                      │
                                          ▼
                               链上 ERC-20 转账
                               （TransferWithAuthorization）
```

### 支付流程（x402 协议）

1. Agent 向付费接口发起 HTTP GET 请求
2. 服务端返回 `402 Payment Required`，携带 EIP-712 支付规格
3. `CawSigner` 将 typed-data 提交给 Cobo MPC 节点进行多方签名
4. 签名后的授权（`TransferWithAuthorization`）附加到重试请求头
5. Facilitator（`x402.org`）验证签名，执行链上 USDC 转账
6. 服务端返回真实区块链数据

### 核心模块

| 文件 | 职责 |
|------|------|
| `agent/agent.py` | DeepSeek LLM 工具调用循环，支付事件跟踪 |
| `agent/tools/caw_signer.py` | Cobo MPC `message_sign` 封装，实现 x402 的 `ClientEvmSigner` 接口 |
| `agent/tools/chain_query.py` | 三个付费查询工具（gas、代币价格、ETH 余额）通过 x402 httpx 调用 |
| `server/main.py` | FastAPI 服务端，内置 x402 收费中间件，返回真实 CoinGecko + RPC 数据 |
| `main.py` | 富文本终端 UI，实时显示支付流水和会话摘要 |

---

## 技术亮点

### 绕过 CAW 内部余额跟踪

CAW 的 `payment()` API 依赖内部余额同步；Agent 钱包的 USDC 是直接打入地址（非通过 Cobo 渠道），内部显示为零。解决方案：直接使用 `message_sign`——x402 Facilitator 直接读取链上余额，完全绕过内部跟踪。

### 线程隔离的异步 MPC 签名

在运行中的 event loop 里调用 CAW 异步客户端会死锁。`CawSigner.sign_typed_data()` 在独立线程中创建新的 event loop 来执行异步签名：

```python
def sign_typed_data(self, domain, types, primary_type, message) -> bytes:
    result_holder = [None]
    def _run():
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self._sign_typed_data_async(...))
    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=120)
```

### bytes 字段序列化

EIP-3009 的 `nonce` 类型为 `bytes32`，无法直接 JSON 序列化。`_to_json_safe()` 递归将所有 `bytes` 值转为 `"0x" + hex` 字符串后再传给 CAW API。

### 顺序执行与静默重试

多个并发 CAW 签名请求会相互冲突。工具调用顺序执行，每次间隔 0.5s；失败后静默等待 1.5s 重试，不向 UI 暴露中间失败状态。

---

## 快速开始

### 前置条件

- Python 3.11+
- Cobo Agentic Wallet 账号，需创建包含 `message_sign` 策略的 Pact（授权 USDC verifyingContract 在 Base Sepolia 上的 EIP-712 签名）
- DeepSeek API Key
- Agent 钱包地址上约 1 USDC（Base Sepolia 测试网）

### 安装依赖

```bash
cd hackathon/chainquery-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 配置环境变量

将 `.env.example` 复制为 `.env` 并填写：

```env
DEEPSEEK_API_KEY=...
AGENT_WALLET_API_KEY=...
AGENT_WALLET_WALLET_ID=...
AGENT_WALLET_ADDRESS=...
SERVER_PRIVATE_KEY=...        # 仅供测试，切勿在主网使用
SERVER_WALLET_ADDRESS=...
```

### 运行

```bash
# 终端 1 — 启动数据服务端
uvicorn server.main:app --port 8000

# 终端 2 — 启动 Agent
PYTHONPATH=. python main.py
```

---

## 数据来源

- **代币价格**：CoinGecko 免费 API（支持 ETH、BTC、USDC、SOL、BNB、MATIC、ARB、OP）
- **Gas 价格**：Base Sepolia 公共 RPC（`eth_gasPrice`、`eth_getBlock`）
- **ETH 余额**：Base Sepolia 公共 RPC（`eth_getBalance`）

---

## 付费 API 接口

所有接口在返回数据前通过 x402 收取 $0.01 USDC。

| 接口 | 数据 |
|------|------|
| `GET /api/token-price/{symbol}` | 代币当前美元价格 |
| `GET /api/gas-price` | 基础费、优先费、综合 gas 价格 |
| `GET /api/eth-balance/{address}` | ETH 余额及美元估值 |
| `GET /api/usdc-balance/{address}` | USDC 余额（Base Sepolia ERC-20）|

---

## 运行 Demo 测试

```bash
# 确保服务端已启动
PYTHONPATH=. python tests/test_demo.py
```

输出包含 4 次付费查询的实时流水，以及会话前后的 USDC 余额对比。

---

## 赛道信息

**Cobo 赛道 01 — Agent-Native Payments**  
演示内容：AI Agent 通过 MPC 钱包 + x402 协议自主为数据付费  
测试网络：Base Sepolia（eip155:84532）  
支付机制：USDC via EIP-3009 `TransferWithAuthorization`  
截止日期：2026 年 6 月 13 日

"""
ChainQuery Agent — DeepSeek LLM + x402 自动付费链上数据查询
"""
import os
import json
import time
import asyncio
from dataclasses import dataclass, field
from typing import Callable, Awaitable
from openai import AsyncOpenAI
from dotenv import load_dotenv

from .tools.chain_query import query_gas_price, query_token_price, query_eth_balance, query_usdc_balance

load_dotenv()

_llm = AsyncOpenAI(
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_gas_price",
            "description": "查询 Base Sepolia 当前 gas 价格。每次调用自动支付 0.01 USDC（x402 协议）。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_token_price",
            "description": "查询指定代币的当前美元价格。每次调用自动支付 0.01 USDC（x402 协议）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "代币符号，例如 ETH、BTC、USDC"},
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_eth_balance",
            "description": "查询某以太坊地址在 Base Sepolia 上的 ETH 余额。每次调用自动支付 0.01 USDC（x402 协议）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "address": {"type": "string", "description": "以太坊钱包地址（0x 开头）"},
                },
                "required": ["address"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_usdc_balance",
            "description": "查询某以太坊地址在 Base Sepolia 上的 USDC 余额。每次调用自动支付 0.01 USDC（x402 协议）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "address": {"type": "string", "description": "以太坊钱包地址（0x 开头）"},
                },
                "required": ["address"],
            },
        },
    },
]

PAYMENT_AMOUNT = 0.01  # USDC per query

TOOL_LABELS = {
    "query_gas_price": "Gas Price",
    "query_token_price": "Token Price",
    "query_eth_balance": "ETH Balance",
    "query_usdc_balance": "USDC Balance",
}


@dataclass
class PaymentEvent:
    tool: str
    args: dict
    result: dict | None
    error: str | None
    duration_ms: int
    amount_usdc: float = PAYMENT_AMOUNT
    tx_hash: str | None = None

    @property
    def label(self) -> str:
        return TOOL_LABELS.get(self.tool, self.tool)

    @property
    def success(self) -> bool:
        return self.error is None


@dataclass
class AgentResult:
    answer: str
    payments: list[PaymentEvent] = field(default_factory=list)

    @property
    def total_spent(self) -> float:
        return sum(p.amount_usdc for p in self.payments if p.success)


# on_payment: async callable receiving PaymentEvent
OnPaymentCallback = Callable[[PaymentEvent], Awaitable[None]]


async def _execute_tool(name: str, args: dict) -> tuple[str, PaymentEvent]:
    """执行单次工具调用，不触发回调（由外层决定何时通知）。"""
    t0 = time.monotonic()
    try:
        if name == "query_gas_price":
            data = await query_gas_price()
        elif name == "query_token_price":
            data = await query_token_price(args["symbol"])
        elif name == "query_eth_balance":
            data = await query_eth_balance(args["address"])
        elif name == "query_usdc_balance":
            data = await query_usdc_balance(args["address"])
        else:
            data = {"error": f"未知工具: {name}"}

        ms = int((time.monotonic() - t0) * 1000)
        tx_hash = data.pop("_tx_hash", None)
        return json.dumps(data, ensure_ascii=False), PaymentEvent(
            tool=name, args=args, result=data, error=None, duration_ms=ms, tx_hash=tx_hash
        )
    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        err_msg = str(e) or type(e).__name__
        return json.dumps({"error": err_msg}, ensure_ascii=False), PaymentEvent(
            tool=name, args=args, result=None, error=err_msg, duration_ms=ms
        )


async def run_agent(
    user_message: str,
    on_payment: OnPaymentCallback | None = None,
    max_spend: float = 0.50,
) -> AgentResult:
    """运行一轮 agent 对话，自动处理 x402 工具调用。"""
    messages = [
        {
            "role": "system",
            "content": (
                "你是 ChainQuery Agent，一个区块链数据助手。"
                "你可以查询 Base Sepolia 上的链上数据（gas 价格、代币价格、钱包余额）。"
                "每次查询通过 x402 协议自动从 Cobo MPC 钱包扣除 0.01 USDC。"
                "用中文简洁地回答用户问题，在回答末尾用一行说明本次共支付多少 USDC。"
            ),
        },
        {"role": "user", "content": user_message},
    ]

    all_payments: list[PaymentEvent] = []

    while True:
        response = await _llm.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )

        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            return AgentResult(answer=msg.content or "", payments=all_payments)

        # 顺序执行，间隔 0.5s 避免 CAW 并发签名冲突
        for i, tc in enumerate(msg.tool_calls):
            # 预算检查：已支出 + 本次费用 > 上限则拒绝
            spent = sum(p.amount_usdc for p in all_payments if p.success)
            if spent + PAYMENT_AMOUNT > max_spend:
                budget_msg = json.dumps({"error": f"会话预算已达上限（${max_spend:.2f} USDC），本次查询取消"})
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": budget_msg})
                for remaining_tc in msg.tool_calls[i + 1:]:
                    messages.append({"role": "tool", "tool_call_id": remaining_tc.id, "content": budget_msg})
                break
            if i > 0:
                await asyncio.sleep(0.5)
            args = json.loads(tc.function.arguments)
            t_start = time.monotonic()
            result_str, event = await _execute_tool(tc.function.name, args)
            # 失败时静默重试一次（不向 UI 暴露中间失败）
            if not event.success:
                await asyncio.sleep(1.5)
                result_str, event = await _execute_tool(tc.function.name, args)
                # 保留总耗时，保留 tx_hash（重试成功时才有值）
                event = PaymentEvent(
                    tool=event.tool, args=event.args,
                    result=event.result, error=event.error,
                    duration_ms=int((time.monotonic() - t_start) * 1000),
                    tx_hash=event.tx_hash,
                )
            # 最终结果才触发回调
            if on_payment:
                await on_payment(event)
            all_payments.append(event)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_str,
            })

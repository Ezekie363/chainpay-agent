"""
ChainQuery Agent — 交互式 Demo
服务器须先运行: uvicorn server.main:app --port 8000
运行: python main.py
"""
import asyncio
import os
import sys
import httpx
from prompt_toolkit import PromptSession
sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv(dotenv_path=".env")

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.rule import Rule
from rich import box

from agent.agent import run_agent, AgentResult, PaymentEvent

console = Console()

WALLET_ADDR = os.environ.get("AGENT_WALLET_ADDRESS", "")
USDC_CONTRACT = os.environ.get("USDC_BASE_SEPOLIA_ADDRESS", "0x036CbD53842c5426634e7929541eC2318f3dCF7e")
RPC_URL = os.environ.get("BASE_SEPOLIA_RPC_URL", "https://sepolia.base.org")
PAYMENT_PER_QUERY = 0.01
SESSION_BUDGET_USDC = 0.05  # 单次会话最大支出上限

# 会话累计
_session_count = 0
_session_spent = 0.0
_session_payments: list[PaymentEvent] = []


async def _get_usdc_balance() -> float:
    """读取 Agent 钱包在 Base Sepolia 的链上 USDC 余额（用 httpx 直接发 eth_call）"""
    try:
        data = "0x70a08231" + WALLET_ADDR[2:].lower().zfill(64)
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "eth_call",
            "params": [{"to": USDC_CONTRACT, "data": data}, "latest"],
        }
        async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
            r = await client.post(RPC_URL, json=payload)
            result = r.json().get("result", "0x0") or "0x0"
            return int(result, 16) / 1e6
    except (Exception, asyncio.CancelledError):
        return -1.0


async def _header():
    console.print(Panel(
        "[bold cyan]ChainQuery Agent[/bold cyan]\n"
        "[dim]AI × Web3 · x402 Protocol · Cobo Agentic Wallet[/dim]\n"
        "[yellow]⚠ Testnet only — Base Sepolia · Test USDC · Not real funds[/yellow]",
        subtitle="[dim]Hackathon Demo — Cobo Track 01[/dim]",
        border_style="cyan",
        padding=(0, 2),
    ))

    with console.status("[dim]读取链上 USDC 余额...[/dim]"):
        bal = await _get_usdc_balance()

    info = Table.grid(padding=(0, 2))
    info.add_column(style="dim")
    info.add_column()
    info.add_row("Agent Wallet", f"[yellow]{WALLET_ADDR}[/yellow]")
    info.add_row("Network", "[green]Base Sepolia (eip155:84532)[/green]")
    info.add_row("USDC Balance", f"[bold white]{bal:.4f} USDC[/bold white]" if bal >= 0 else "[dim]查询失败[/dim]")
    info.add_row("Payment", "[white]0.01 USDC per query  ·  x402 + CAW MPC[/white]")
    console.print(info)
    console.print()
    return bal


def _payment_event_display(event: PaymentEvent) -> Text:
    if event.success:
        label = f"[green]✔[/green] [bold]{event.label}[/bold]"
        detail = _format_result(event.tool, event.result)
        return Text.from_markup(
            f"{label}  [dim]({event.duration_ms} ms)[/dim]  "
            f"[cyan]−${PAYMENT_PER_QUERY:.2f} USDC[/cyan]  {detail}"
        )
    else:
        return Text.from_markup(
            f"[red]✗[/red] [bold]{event.label}[/bold]  "
            f"[red]{event.error[:60]}[/red]"
        )


def _format_result(tool: str, result: dict | None) -> str:
    if not result:
        return ""
    if tool == "query_gas_price":
        return f"[white]{result.get('gasPrice', '')}[/white]"
    if tool == "query_token_price":
        sym = result.get("symbol", "")
        price = result.get("price_usd", "")
        return f"[bold white]{sym} = ${price:,.2f}[/bold white]" if isinstance(price, (int, float)) else f"[white]{price}[/white]"
    if tool == "query_eth_balance":
        bal = result.get("balance_eth", "")
        return f"[bold white]{bal} ETH[/bold white]"
    if tool == "query_usdc_balance":
        bal = result.get("balance_usdc", "")
        return f"[bold white]{bal} USDC[/bold white]"
    return ""


async def _ask(question: str) -> AgentResult:
    global _session_count, _session_spent

    console.print()
    payments_shown: list[PaymentEvent] = []

    async def on_payment(event: PaymentEvent):
        payments_shown.append(event)
        console.print(Text("  ") + _payment_event_display(event))
        if event.success and event.tx_hash:
            console.print(f"     [dim]tx[/dim] [cyan]{event.tx_hash}[/cyan]")

    # 预算检查
    remaining = SESSION_BUDGET_USDC - _session_spent
    if remaining <= 0:
        console.print(f"  [red]⚠ 会话预算已用完（上限 ${SESSION_BUDGET_USDC:.2f} USDC），请重启 Agent[/red]\n")
        return AgentResult(answer="", payments=[])

    # spinner 提示 agent 正在思考
    with console.status("[dim]Agent thinking...[/dim]", spinner="dots"):
        result = await run_agent(question, on_payment=on_payment, max_spend=remaining)

    _session_count += 1
    _session_spent += result.total_spent
    _session_payments.extend(result.payments)

    # 打印 agent 回答
    console.print()
    console.print(Panel(
        result.answer,
        title="[bold green]Agent[/bold green]",
        border_style="green",
        padding=(0, 1),
    ))

    # 本轮支付摘要
    if result.payments:
        paid = sum(p.amount_usdc for p in result.payments if p.success)
        calls = len([p for p in result.payments if p.success])
        console.print(
            f"  本轮：[white]{calls} 次查询[/white]  ·  "
            f"支付 [bold cyan]${paid:.2f} USDC[/bold cyan]  ·  "
            f"会话累计 [bold cyan]${_session_spent:.2f} USDC[/bold cyan]"
        )

    console.print()
    return result


async def _session_summary(start_balance: float):
    if not _session_payments:
        return
    console.print(Rule("[bold]会话摘要[/bold]"))
    tbl = Table(box=box.SIMPLE, show_header=True, header_style="bold white")
    tbl.add_column("#", style="dim", width=3)
    tbl.add_column("工具", style="bold white")
    tbl.add_column("参数", style="white")
    tbl.add_column("耗时", justify="right", style="dim")
    tbl.add_column("费用", justify="right", style="bold cyan")
    tbl.add_column("交易哈希", style="cyan")
    tbl.add_column("状态", justify="center")

    for i, p in enumerate(_session_payments, 1):
        args_str = ", ".join(f"{k}={v}" for k, v in p.args.items()) or "—"
        status = "[green]✔[/green]" if p.success else "[red]✗[/red]"
        tx_display = p.tx_hash if p.tx_hash else "[dim]—[/dim]"
        tbl.add_row(
            str(i), p.label, args_str,
            f"{p.duration_ms} ms", f"${p.amount_usdc:.2f}", tx_display, status,
        )

    console.print(tbl)

    # 会话结束后查一次余额对比
    with console.status("[dim]查询结束余额...[/dim]"):
        end_balance = await _get_usdc_balance()

    info = Table.grid(padding=(0, 2))
    info.add_column(style="white")
    info.add_column()
    info.add_row("查询次数", f"[bold white]{len(_session_payments)}[/bold white] 次")
    info.add_row("本次支付", f"[bold cyan]${_session_spent:.2f} USDC[/bold cyan]")
    if start_balance >= 0 and end_balance >= 0:
        info.add_row(
            "钱包余额",
            f"[white]{start_balance:.4f}[/white] → [bold white]{end_balance:.4f} USDC[/bold white]"
            f"  [dim](−{start_balance - end_balance:.4f})[/dim]",
        )
    info.add_row("支付方式", "[bold]Cobo MPC Wallet  ·  x402 Protocol  ·  Base Sepolia[/bold]")
    console.print(info)
    console.print()


EXAMPLES = [
    "现在 ETH 的价格是多少？",
    "查询 BTC 和 ETH 的价格，以及当前 gas 费用",
    f"帮我查询地址 {WALLET_ADDR} 的 ETH 和 USDC 余额",
    "我想知道 gas 现在贵不贵，值不值得发交易",
]


async def main():
    start_balance = await _header()

    console.print("[dim]示例问题：[/dim]")
    for i, ex in enumerate(EXAMPLES, 1):
        console.print(f"  [dim]{i}.[/dim] {ex}")
    console.print()
    console.print("[dim]输入问题后按 Enter，输入 exit 退出[/dim]\n")

    _prompt = PromptSession()
    while True:
        try:
            question = (await _prompt.prompt_async("You: ")).strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not question:
            continue
        if question.lower() in ("exit", "quit", "退出", "q"):
            break

        await _ask(question)

    await _session_summary(start_balance)
    console.print("[dim]感谢使用 ChainQuery Agent！[/dim]\n")


if __name__ == "__main__":
    asyncio.run(main())

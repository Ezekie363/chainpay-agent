"""测试 demo UI 输出效果（非交互式）"""
import asyncio, sys
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(dotenv_path=".env")

import main as demo


async def run():
    start_bal = await demo._header()
    await demo._ask("ETH 和 BTC 的价格分别是多少？顺便查一下当前 gas。")
    await demo._ask(f"查询地址 {demo.WALLET_ADDR} 的余额")
    await demo._session_summary(start_bal)


asyncio.run(run())

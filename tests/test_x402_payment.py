"""
测试 CAW payment API 完整 x402 流程：402 → payment → 重试 → 数据
服务器必须先运行: uvicorn server.main:app --port 8000
运行: PYTHONPATH=. .venv/bin/python tests/test_x402_payment.py
"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from agent.tools.chain_query import query_gas_price, query_token_price


async def main():
    print("=== 测试 x402 完整支付流程 ===\n")

    print("[1] 查询 Gas Price (需支付 0.01 USDC)...")
    try:
        result = await query_gas_price()
        print(f"    成功! gasPrice={result.get('gasPrice')}, network={result.get('network')}")
    except Exception as e:
        import traceback
        print(f"    失败: {type(e).__name__}: {e}")
        traceback.print_exc()

    print("\n[2] 查询 ETH 价格 (需支付 0.01 USDC)...")
    try:
        result = await query_token_price("ETH")
        print(f"    成功! price=${result.get('price_usd')}")
    except Exception as e:
        print(f"    失败: {e}")

    print("\n完成")


asyncio.run(main())

"""
验证 CAW SDK 能正常连接钱包并读取余额
运行: python tests/test_caw_connection.py
"""
import asyncio
import os
from dotenv import load_dotenv
from cobo_agentic_wallet.client import WalletAPIClient

load_dotenv()

API_URL = os.environ["AGENT_WALLET_API_URL"]
API_KEY = os.environ["AGENT_WALLET_API_KEY"]
WALLET_ID = os.environ["AGENT_WALLET_WALLET_ID"]


async def main():
    async with WalletAPIClient(base_url=API_URL, api_key=API_KEY) as client:
        print(f"连接到: {API_URL}")
        print(f"钱包 ID: {WALLET_ID}")

        balances = await client.list_balances(wallet_uuid=WALLET_ID)
        print("\n当前余额:")
        for b in balances:
            print(f"  {b['token_id']}: {b['amount']}")

        print("\nCAW SDK 连接成功 ✓")


asyncio.run(main())

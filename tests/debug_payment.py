"""调试 CAW payment API 每步输出"""
import asyncio, os, uuid, sys
sys.path.insert(0, ".")
import httpx
from dotenv import load_dotenv
load_dotenv(dotenv_path=".env")
from cobo_agentic_wallet.client import WalletAPIClient

WALLET_ID = os.environ["AGENT_WALLET_WALLET_ID"]
API_URL = os.environ["AGENT_WALLET_API_URL"]
API_KEY = os.environ["AGENT_WALLET_API_KEY"]
URL = "http://localhost:8000/api/gas-price"


async def test():
    print("Step 1: 发送初始请求...")
    async with httpx.AsyncClient(timeout=30, trust_env=False) as http:
        resp = await http.get(URL)
    print(f"  状态码: {resp.status_code}")
    if resp.status_code != 402:
        print(f"  非 402: {resp.text[:200]}")
        return
    payment_required = resp.headers.get("payment-required")
    print(f"  payment-required 头 OK，长度={len(payment_required)}")

    print("Step 2: 调用 CAW payment API...")
    try:
        async with WalletAPIClient(base_url=API_URL, api_key=API_KEY) as client:
            result = await client.payment(
                wallet_uuid=WALLET_ID, protocol="x402",
                x402_payment_required=payment_required,
                request_id=str(uuid.uuid4()),
            )
        print(f"  结果类型: {type(result).__name__}")
        if isinstance(result, dict):
            print(f"  结果: {result}")
        else:
            d = result.to_dict() if hasattr(result, "to_dict") else vars(result)
            print(f"  结果: {d}")
    except Exception as e:
        import traceback
        print(f"  错误类型: {type(e).__name__}")
        print(f"  错误: {e}")
        traceback.print_exc()


asyncio.run(test())

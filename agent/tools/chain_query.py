"""
x402 付费 HTTP 客户端 — 用 CawSigner + x402-python ExactEvmScheme 完成支付流程

流程：
  1. GET url → 402 + payment-required 头
  2. CawSigner 对 EIP-712 TransferWithAuthorization 签名（MPC，轮询等待）
  3. 携带 X-PAYMENT 头重试 → 服务器验证链上余额并放行
  4. on_payment_response hook 捕获 SettleResponse.transaction（交易哈希）
"""
import os
from dotenv import load_dotenv
from x402.client import x402Client, x402ClientConfig, SchemeRegistration
from x402.mechanisms.evm.exact.client import ExactEvmScheme
from x402.http.clients.httpx import x402HttpxClient
from .caw_signer import make_caw_signer

load_dotenv()

BASE_URL = os.environ.get("CHAIN_DATA_SERVER_URL", "http://localhost:8000")


def _make_x402_client() -> x402Client:
    signer = make_caw_signer()
    config = x402ClientConfig(
        schemes=[
            SchemeRegistration(
                network="eip155:84532",
                client=ExactEvmScheme(signer=signer),
            )
        ]
    )
    return x402Client.from_config(config)


async def _query(url: str) -> dict:
    """通用付费查询：走 x402 流程，结果中附带 _tx_hash 字段。"""
    tx_hash_holder: list[str | None] = [None]

    x402 = _make_x402_client()

    @x402.on_payment_response
    async def _capture_tx(ctx):
        sr = getattr(ctx, "settle_response", None)
        if sr and getattr(sr, "transaction", None):
            tx_hash_holder[0] = sr.transaction

    async with x402HttpxClient(x402, trust_env=False) as http:
        resp = await http.get(url)
        resp.raise_for_status()
        data = resp.json()

    if tx_hash_holder[0]:
        data["_tx_hash"] = tx_hash_holder[0]
    return data


async def query_gas_price() -> dict:
    return await _query(f"{BASE_URL}/api/gas-price")


async def query_token_price(symbol: str) -> dict:
    return await _query(f"{BASE_URL}/api/token-price/{symbol}")


async def query_eth_balance(address: str) -> dict:
    return await _query(f"{BASE_URL}/api/eth-balance/{address}")


async def query_usdc_balance(address: str) -> dict:
    return await _query(f"{BASE_URL}/api/usdc-balance/{address}")

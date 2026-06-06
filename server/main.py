"""
ChainData API Server — 带 x402 收费中间件，返回真实链上/市场数据

数据来源：
  - Gas 价格：Base Sepolia 公共 RPC（eth_gasPrice）
  - 代币价格：CoinGecko 免费 API
  - ETH 余额：Base Sepolia 公共 RPC（eth_getBalance）
"""
import os
import httpx
from web3 import Web3
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from x402.server import x402ResourceServer
from x402.http.facilitator_client import HTTPFacilitatorClient
from x402.http.middleware.fastapi import payment_middleware
from x402.mechanisms.evm.exact.register import register_exact_evm_server

load_dotenv()

SERVER_WALLET_ADDRESS = os.environ["SERVER_WALLET_ADDRESS"]
NETWORK = "eip155:84532"
BASE_SEPOLIA_RPC = os.environ.get("BASE_SEPOLIA_RPC_URL", "https://sepolia.base.org")

app = FastAPI(title="ChainData API", description="x402 付费链上数据 API")

facilitator = HTTPFacilitatorClient()
server = x402ResourceServer(facilitator)
register_exact_evm_server(server)

routes = {
    "GET /api/gas-price": {
        "accepts": {"scheme": "exact", "payTo": SERVER_WALLET_ADDRESS, "price": "$0.01", "network": NETWORK}
    },
    "GET /api/token-price/*": {
        "accepts": {"scheme": "exact", "payTo": SERVER_WALLET_ADDRESS, "price": "$0.01", "network": NETWORK}
    },
    "GET /api/eth-balance/*": {
        "accepts": {"scheme": "exact", "payTo": SERVER_WALLET_ADDRESS, "price": "$0.01", "network": NETWORK}
    },
    "GET /api/usdc-balance/*": {
        "accepts": {"scheme": "exact", "payTo": SERVER_WALLET_ADDRESS, "price": "$0.01", "network": NETWORK}
    },
}


@app.middleware("http")
async def x402_middleware(request: Request, call_next):
    return await payment_middleware(routes, server)(request, call_next)


# ── 真实数据获取 ────────────────────────────────────────────────────────────

_w3 = Web3(Web3.HTTPProvider(BASE_SEPOLIA_RPC))

# CoinGecko ID 映射
_COINGECKO_IDS = {
    "ETH": "ethereum",
    "BTC": "bitcoin",
    "USDC": "usd-coin",
    "SOL": "solana",
    "BNB": "binancecoin",
    "MATIC": "matic-network",
    "ARB": "arbitrum",
    "OP": "optimism",
}


async def _fetch_token_price(symbol: str) -> float:
    cg_id = _COINGECKO_IDS.get(symbol.upper())
    if not cg_id:
        return 0.0
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers={"Accept": "application/json"})
        data = resp.json()
        return data.get(cg_id, {}).get("usd", 0.0)


def _fetch_gas_price() -> dict:
    try:
        gas_wei = _w3.eth.gas_price
        base_fee_wei = _w3.eth.get_block("latest").get("baseFeePerGas", 0)
        priority_wei = max(0, gas_wei - base_fee_wei)
        to_gwei = lambda w: round(w / 1e9, 2)
        return {
            "gasPrice": f"{to_gwei(gas_wei)} gwei",
            "baseFee": f"{to_gwei(base_fee_wei)} gwei",
            "priorityFee": f"{to_gwei(priority_wei)} gwei",
            "network": "Base Sepolia",
        }
    except Exception as e:
        return {"gasPrice": "N/A", "baseFee": "N/A", "priorityFee": "N/A", "network": "Base Sepolia", "error": str(e)}


# ── 路由 ────────────────────────────────────────────────────────────────────

@app.get("/api/gas-price")
async def get_gas_price():
    return _fetch_gas_price()


@app.get("/api/token-price/{symbol}")
async def get_token_price(symbol: str):
    price = await _fetch_token_price(symbol)
    return {"symbol": symbol.upper(), "price_usd": price, "currency": "USD"}


@app.get("/api/eth-balance/{address}")
async def get_eth_balance(address: str):
    try:
        checksum = Web3.to_checksum_address(address)
        bal_wei = _w3.eth.get_balance(checksum)
        bal_eth = bal_wei / 1e18
        # 顺带取 ETH 价格估算美元价值
        eth_price = await _fetch_token_price("ETH")
        return {
            "address": address,
            "balance_eth": f"{bal_eth:.6f}",
            "balance_usd": round(bal_eth * eth_price, 2),
            "network": "Base Sepolia",
        }
    except Exception as e:
        return {"address": address, "balance_eth": "0", "balance_usd": 0, "network": "Base Sepolia", "error": str(e)}


_USDC_ADDRESS = os.environ.get("USDC_BASE_SEPOLIA_ADDRESS", "0x036CbD53842c5426634e7929541eC2318f3dCF7e")
_USDC_ABI = [{"name": "balanceOf", "type": "function",
               "inputs": [{"name": "a", "type": "address"}],
               "outputs": [{"name": "", "type": "uint256"}],
               "stateMutability": "view"}]


@app.get("/api/usdc-balance/{address}")
async def get_usdc_balance(address: str):
    try:
        checksum = Web3.to_checksum_address(address)
        contract = _w3.eth.contract(address=Web3.to_checksum_address(_USDC_ADDRESS), abi=_USDC_ABI)
        raw = contract.functions.balanceOf(checksum).call()
        usdc = raw / 1e6
        return {
            "address": address,
            "balance_usdc": round(usdc, 6),
            "network": "Base Sepolia",
            "contract": _USDC_ADDRESS,
        }
    except Exception as e:
        return {"address": address, "balance_usdc": 0, "network": "Base Sepolia", "error": str(e)}


@app.get("/health")
async def health():
    return {"status": "ok"}

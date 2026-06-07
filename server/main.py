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

_PAID = {"scheme": "exact", "payTo": SERVER_WALLET_ADDRESS, "price": "$0.01", "network": NETWORK}

routes = {
    "GET /api/gas-price":      {"accepts": _PAID},
    "GET /api/token-price/*":  {"accepts": _PAID},
    "GET /api/eth-balance/*":  {"accepts": _PAID},
    "GET /api/usdc-balance/*": {"accepts": _PAID},
    "GET /api/defi-tvl/*":     {"accepts": _PAID},
    "GET /api/fear-greed":     {"accepts": _PAID},
}


@app.middleware("http")
async def x402_middleware(request: Request, call_next):
    return await payment_middleware(routes, server)(request, call_next)


# ── 真实数据获取 ────────────────────────────────────────────────────────────

_w3 = Web3(Web3.HTTPProvider(BASE_SEPOLIA_RPC))

# CoinGecko ID 映射
_COINGECKO_IDS = {
    # L1 主链
    "ETH":  "ethereum",
    "BTC":  "bitcoin",
    "SOL":  "solana",
    "BNB":  "binancecoin",
    "AVAX": "avalanche-2",
    "DOT":  "polkadot",
    "ADA":  "cardano",
    "XRP":  "ripple",
    "ATOM": "cosmos",
    "NEAR": "near",
    "APT":  "aptos",
    "SUI":  "sui",
    "INJ":  "injective-protocol",
    "SEI":  "sei-network",
    # L2 / Rollup
    "MATIC": "matic-network",
    "ARB":   "arbitrum",
    "OP":    "optimism",
    "STRK":  "starknet",
    # Stablecoin
    "USDC": "usd-coin",
    "USDT": "tether",
    "DAI":  "dai",
    "ENA":  "ethena",
    # Wrapped / LST
    "WBTC":  "wrapped-bitcoin",
    "STETH": "staked-ether",
    # DeFi
    "LINK":   "chainlink",
    "UNI":    "uniswap",
    "AAVE":   "aave",
    "CRV":    "curve-dao-token",
    "GMX":    "gmx",
    "PENDLE": "pendle",
    # Meme
    "DOGE": "dogecoin",
    "SHIB": "shiba-inu",
    "PEPE": "pepe",
    "WIF":  "dogwifcoin",
    # AI
    "WLD": "worldcoin-wld",
}


async def _fetch_token_price(symbol: str) -> dict:
    cg_id = _COINGECKO_IDS.get(symbol.upper())
    if not cg_id:
        return {"price_usd": 0.0, "change_24h": None}
    url = (
        f"https://api.coingecko.com/api/v3/simple/price"
        f"?ids={cg_id}&vs_currencies=usd&include_24hr_change=true"
    )
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers={"Accept": "application/json"})
        entry = resp.json().get(cg_id, {})
        return {
            "price_usd": entry.get("usd", 0.0),
            "change_24h": round(entry.get("usd_24h_change", 0.0), 2),
        }


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
    result = await _fetch_token_price(symbol)
    return {"symbol": symbol.upper(), "price_usd": result["price_usd"],
            "change_24h": result["change_24h"], "currency": "USD"}


@app.get("/api/eth-balance/{address}")
async def get_eth_balance(address: str):
    try:
        checksum = Web3.to_checksum_address(address)
        bal_wei = _w3.eth.get_balance(checksum)
        bal_eth = bal_wei / 1e18
        # 顺带取 ETH 价格估算美元价值
        eth_price = (await _fetch_token_price("ETH"))["price_usd"]
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


_DEFI_SLUGS = {
    "UNISWAP":     "uniswap",
    "AAVE":        "aave",
    "MAKERDAO":    "makerdao",
    "LIDO":        "lido",
    "COMPOUND":    "compound",
    "CURVE":       "curve",
    "PANCAKESWAP": "pancakeswap",
    "GMX":         "gmx",
    "DYDX":        "dydx",
    "PENDLE":      "pendle",
    "MORPHO":      "morpho",
    "SKY":         "sky",
}


def _fmt_tvl(usd: float) -> str:
    if usd >= 1e9:
        return f"${usd / 1e9:.2f}B"
    if usd >= 1e6:
        return f"${usd / 1e6:.1f}M"
    return f"${usd:,.0f}"


@app.get("/api/defi-tvl/{protocol}")
async def get_defi_tvl(protocol: str):
    slug = _DEFI_SLUGS.get(protocol.upper(), protocol.lower())
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://api.llama.fi/tvl/{slug}",
                headers={"Accept": "application/json"},
            )
            tvl = float(resp.text)
        return {"protocol": protocol.upper(), "slug": slug,
                "tvl_usd": round(tvl, 2), "tvl_formatted": _fmt_tvl(tvl)}
    except Exception as e:
        return {"protocol": protocol.upper(), "tvl_usd": 0, "error": str(e)}


@app.get("/api/fear-greed")
async def get_fear_greed():
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.alternative.me/fng/?limit=1",
                headers={"Accept": "application/json"},
            )
            entry = resp.json()["data"][0]
        return {
            "value": int(entry["value"]),
            "classification": entry["value_classification"],
            "description": "0=极度恐惧 / 100=极度贪婪",
        }
    except Exception as e:
        return {"value": -1, "classification": "N/A", "error": str(e)}


@app.get("/health")
async def health():
    return {"status": "ok"}

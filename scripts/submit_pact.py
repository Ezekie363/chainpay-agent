"""
提交 ChainQuery Agent 的 Pact（14天有效期）
运行: PYTHONPATH=. python scripts/submit_pact.py

如果当前 AGENT_WALLET_API_KEY 是 pact-scoped key（caw_ 开头且已被撤销），
需要换成你在 Cobo Portal 创建的 root API key 再运行本脚本。
"""
import asyncio
import os
import json
from dotenv import load_dotenv

load_dotenv()

API_URL = os.environ["AGENT_WALLET_API_URL"]
API_KEY = os.environ["AGENT_WALLET_API_KEY"]
WALLET_ID = os.environ["AGENT_WALLET_WALLET_ID"]
WALLET_ADDR = os.environ["AGENT_WALLET_ADDRESS"]

# 14 天 = 1209600 秒
DURATION_SECONDS = str(14 * 24 * 3600)

# Base Sepolia USDC verifyingContract
USDC_CONTRACT = os.environ.get(
    "USDC_BASE_SEPOLIA_ADDRESS",
    "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
)


async def main():
    from cobo_agentic_wallet.client import WalletAPIClient

    print(f"API URL : {API_URL}")
    print(f"Wallet  : {WALLET_ID}")
    print(f"Address : {WALLET_ADDR}")
    print(f"Duration: 14 天 ({DURATION_SECONDS}s)\n")

    async with WalletAPIClient(base_url=API_URL, api_key=API_KEY) as client:
        result = await client.submit_pact(
            wallet_id=WALLET_ID,
            name="ChainQuery Agent — x402 message_sign (14d)",
            intent=(
                "ChainQuery Agent 需要对 Base Sepolia 上的 USDC TransferWithAuthorization "
                "EIP-712 消息进行签名，用于通过 x402 协议完成微支付数据查询。"
                "每次查询支付 0.01 USDC，会话上限 0.05 USDC。"
            ),
            spec={
                "policies": [
                    {
                        "name": "allow-usdc-transfer-auth",
                        "type": "message_sign",
                        "rules": {
                            "effect": "allow",
                            "when": {
                                "chain_in": ["TBASE_SETH"],
                                "primary_type_in": ["TransferWithAuthorization"],
                                "source_address_in": [
                                    {
                                        "chain_id": "TBASE_SETH",
                                        "address": WALLET_ADDR,
                                    }
                                ],
                                "domain_match": [
                                    {
                                        "param_name": "verifyingContract",
                                        "op": "eq",
                                        "value": USDC_CONTRACT,
                                    }
                                ],
                            },
                        },
                    }
                ],
                "completion_conditions": [
                    {
                        "type": "time_elapsed",
                        "threshold": DURATION_SECONDS,
                    }
                ],
                "execution_plan": (
                    "# Summary\n"
                    "对 Base Sepolia USDC 合约的 TransferWithAuthorization EIP-712 消息签名，\n"
                    "用于 x402 协议微支付（每次 0.01 USDC）。\n\n"
                    "# Contract Operations\n"
                    f"- verifyingContract: {USDC_CONTRACT}\n"
                    "- primaryType: TransferWithAuthorization\n"
                    "- chain: TBASE_SETH (Base Sepolia)\n\n"
                    "# Risk Controls\n"
                    "- 仅允许 TransferWithAuthorization，不授权其他操作\n"
                    "- 仅限指定 verifyingContract\n"
                    "- 14 天后自动过期\n\n"
                    "# Schedule\n"
                    f"有效期：{DURATION_SECONDS}s（14天）"
                ),
            },
        )

    print("Pact 提交成功！")
    print(json.dumps(result if isinstance(result, dict) else vars(result), indent=2, default=str))
    print("\n请在 Cobo Guard App 或 Portal 审批页面确认审批。")


asyncio.run(main())

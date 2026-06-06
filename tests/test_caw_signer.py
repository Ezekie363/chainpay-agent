"""
测试 CAW Signer 能否正确对 EIP-712 数据签名
运行: python tests/test_caw_signer.py
"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

# 使用 pact-scoped API key
os.environ["AGENT_WALLET_API_KEY"] = "caw_D4SEahQ_zlVfwLr2EHkqHzvsQnoU5Sc-fXX-Qf4aweE"

from agent.tools.caw_signer import make_caw_signer


async def main():
    signer = make_caw_signer()
    print(f"Signer 地址: {signer.address}")

    # 构造一个最简 EIP-712 测试消息
    from x402.mechanisms.evm.types import TypedDataDomain, TypedDataField

    domain = TypedDataDomain(
        name="USDC",
        version="2",
        chain_id=84532,
        verifying_contract="0x036CbD53842c5426634e7929541eC2318f3dCF7e",
    )
    types = {
        "TransferWithAuthorization": [
            TypedDataField(name="from", type="address"),
            TypedDataField(name="to", type="address"),
            TypedDataField(name="value", type="uint256"),
            TypedDataField(name="validAfter", type="uint256"),
            TypedDataField(name="validBefore", type="uint256"),
            TypedDataField(name="nonce", type="bytes32"),
        ]
    }
    message = {
        "from": signer.address,
        "to": "0x914e827603F7DafFB59EB7993C8B2eF41e5da20c",
        "value": 10000,
        "validAfter": 0,
        "validBefore": 9999999999,
        "nonce": "0x" + "00" * 32,
    }

    print("正在向 CAW 请求 EIP-712 签名...")
    sig = await signer._sign_typed_data_async(domain, types, "TransferWithAuthorization", message)
    print(f"签名成功! 长度: {len(sig)} bytes")
    print(f"签名(hex): 0x{sig.hex()[:40]}...")


asyncio.run(main())

"""
CAW Signer — 实现 x402 ClientEvmSigner 协议，用 Cobo Agentic Wallet MPC 签名

关键：签名是异步的（MPC 多节点），提交后需轮询直到 status=900（成功）。
不依赖 CAW 内部余额跟踪，facilitator 直接查链上余额。
"""
import asyncio
import uuid
import os
from typing import Any
from cobo_agentic_wallet.client import WalletAPIClient
from x402.mechanisms.evm.types import TypedDataDomain, TypedDataField

_STATUS_SUCCESS = 900
_STATUS_FAILED = {901, 902}  # failed / rejected
_POLL_INTERVAL = 1.5  # seconds
_MAX_POLLS = 30  # 45 seconds total


class CawSigner:
    """把 CAW MPC 钱包包装成 x402 ClientEvmSigner。

    sign_typed_data 提交 EIP-712 签名请求后轮询，直到 MPC 签名完成返回结果。
    不做内部余额检查——facilitator 会直接验证链上余额。
    """

    def __init__(self, wallet_uuid, address, api_url, api_key, chain_id="TBASE_SETH"):
        self._wallet_uuid = wallet_uuid
        self._address = address
        self._api_url = api_url
        self._api_key = api_key
        self._chain_id = chain_id

    @property
    def address(self) -> str:
        return self._address

    def sign_typed_data(
        self,
        domain: TypedDataDomain,
        types: dict[str, list[TypedDataField]],
        primary_type: str,
        message: dict[str, Any],
    ) -> bytes:
        """同步包装，供 x402 同步调用。

        无论当前是否在 async 上下文，都在独立线程+独立事件循环中执行，
        避免与外部 event loop 死锁。
        """
        import threading

        result_holder: list = [None]
        error_holder: list = [None]

        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result_holder[0] = loop.run_until_complete(
                    self._sign_typed_data_async(domain, types, primary_type, message)
                )
            except Exception as exc:
                error_holder[0] = exc
            finally:
                loop.close()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(timeout=120)  # 最多等 120 秒

        if thread.is_alive():
            raise TimeoutError("CAW message_sign 超时（120s）")
        if error_holder[0]:
            raise error_holder[0]
        return result_holder[0]

    async def _sign_typed_data_async(
        self,
        domain: TypedDataDomain,
        types: dict[str, list[TypedDataField]],
        primary_type: str,
        message: dict[str, Any],
    ) -> bytes:
        domain_dict = {k: v for k, v in {
            "name": getattr(domain, "name", None),
            "version": getattr(domain, "version", None),
            "chainId": getattr(domain, "chain_id", None) or getattr(domain, "chainId", None),
            "verifyingContract": (
                getattr(domain, "verifying_contract", None) or
                getattr(domain, "verifyingContract", None)
            ),
        }.items() if v is not None}

        types_dict = {}
        for type_name, fields in types.items():
            types_dict[type_name] = [
                {"name": f.name if hasattr(f, "name") else f["name"],
                 "type": f.type if hasattr(f, "type") else f["type"]}
                for f in fields
            ]

        # JSON 不能序列化 bytes，转为 0x 开头的 hex 字符串
        def _to_json_safe(v):
            if isinstance(v, bytes):
                return "0x" + v.hex()
            if isinstance(v, dict):
                return {k: _to_json_safe(val) for k, val in v.items()}
            if isinstance(v, list):
                return [_to_json_safe(i) for i in v]
            return v

        eip712_payload = {
            "domain": domain_dict,
            "types": types_dict,
            "primaryType": primary_type,
            "message": _to_json_safe(message),
        }

        req_id = str(uuid.uuid4())

        async with WalletAPIClient(base_url=self._api_url, api_key=self._api_key) as client:
            # 提交签名请求
            result = await client.message_sign(
                wallet_uuid=self._wallet_uuid,
                chain_id=self._chain_id,
                eip712_typed_data=eip712_payload,
                source_address=self._address,
                description=f"x402 payment ({primary_type})",
                request_id=req_id,
            )

            # 用相同 request_id 轮询直到完成
            for _ in range(_MAX_POLLS):
                status = result.get("status") if isinstance(result, dict) else getattr(result, "status", None)
                sig = result.get("signature") if isinstance(result, dict) else getattr(result, "signature", None)

                if status == _STATUS_SUCCESS and sig:
                    break
                if status in _STATUS_FAILED:
                    raise ValueError(f"CAW message_sign 被拒绝/失败: status={status}, result={result}")

                await asyncio.sleep(_POLL_INTERVAL)
                # 用同一 request_id 重新请求，获取最新状态（幂等接口）
                result = await client.message_sign(
                    wallet_uuid=self._wallet_uuid,
                    chain_id=self._chain_id,
                    eip712_typed_data=eip712_payload,
                    source_address=self._address,
                    description=f"x402 payment ({primary_type})",
                    request_id=req_id,
                )
            else:
                raise TimeoutError(f"CAW message_sign 超时（{_MAX_POLLS * _POLL_INTERVAL}s），最后状态={status}")

        sig_hex = sig if isinstance(sig, str) else ""
        if sig_hex.startswith("0x"):
            sig_hex = sig_hex[2:]
        return bytes.fromhex(sig_hex)


def make_caw_signer() -> CawSigner:
    """从环境变量创建 CawSigner 实例"""
    return CawSigner(
        wallet_uuid=os.environ["AGENT_WALLET_WALLET_ID"],
        address=os.environ["AGENT_WALLET_ADDRESS"],
        api_url=os.environ["AGENT_WALLET_API_URL"],
        api_key=os.environ["AGENT_WALLET_API_KEY"],
        chain_id="TBASE_SETH",
    )

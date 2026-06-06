"""快速测试 DeepSeek agent + x402 工具调用"""
import asyncio
import sys
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(dotenv_path=".env")

from agent.agent import run_agent


async def main():
    print("=== ChainQuery Agent 测试 ===\n")
    question = "现在 ETH 的价格是多少？顺便帮我查一下 gas 价格。"
    print(f"用户: {question}\n")
    answer = await run_agent(question)
    print(f"\nAgent: {answer}")


asyncio.run(main())

import asyncio
import os
from typing import Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAI


class GroqAIAgent:
    """
    Lightweight Groq (OpenAI-compatible) client for fallback fixes.
    """

    def __init__(self):
        load_dotenv()

        self.api_key = os.getenv("GROQ_API_KEY") or os.getenv("GROQ_KEY") or ""

        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY is required; set it in environment or .env")

        self.client: Optional[OpenAI] = OpenAI(
            api_key=self.api_key,
            base_url="https://api.groq.com/openai/v1",
        )

        self.async_client: Optional[AsyncOpenAI] = AsyncOpenAI(
            api_key=self.api_key,
            base_url="https://api.groq.com/openai/v1",
        )

        self.timeout = 60
        self.model = "openai/gpt-oss-20b"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def fix_file(self, file_path: str, bug_type: str, line_no: int) -> bool:
        """
        Safe sync wrapper.
        """
        try:
            return asyncio.run(self.fix_file_async(file_path, bug_type, line_no))
        except RuntimeError:
            # If already inside event loop, user must call async version directly
            return False
        except Exception:
            return False

    async def fix_file_async(self, file_path: str, bug_type: str, line_no: int) -> bool:
        if not self.async_client:
            return False

        try:
            if not os.path.exists(file_path):
                return False

            with open(file_path, "r", encoding="utf-8") as f:
                source = f.read()

            prompt = self._build_prompt(source, bug_type, line_no)

            resp = await asyncio.wait_for(
                self.async_client.responses.create(
                    model=self.model,
                    input=prompt,
                ),
                timeout=self.timeout,
            )

            fixed = resp.output_text.strip() + "\n"

            if not fixed or fixed.strip() == source.strip():
                return False

            # Validate Python syntax before writing
            if file_path.endswith(".py"):
                try:
                    compile(fixed, file_path, "exec")
                except SyntaxError:
                    return False

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(fixed)

            return True

        except Exception:
            return False

    def _build_prompt(self, source: str, bug_type: str, line_no: int) -> str:
        return (
            "Return only the full corrected file. No explanations.\n"
            f"Bug type: {bug_type}\n"
            f"Likely failing line: {line_no}\n"
            "Rules:\n"
            "- Keep structure and intent\n"
            "- Minimal safe fixes\n"
            "- No markdown\n"
            "- Return complete file\n\n"
            "File:\n"
            f"{source}"
        )

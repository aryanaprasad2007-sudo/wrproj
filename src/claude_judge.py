"""
Cloud tie-breaker. Only called when the local detector returns "unsure",
so most frames never leave the machine.
"""
import base64
import os

import cv2

try:
    import anthropic
except Exception:
    anthropic = None


class ClaudeJudge:
    def __init__(self, model, productive_definition):
        self.model = model
        self.definition = productive_definition
        self.client = None
        if anthropic is not None and os.environ.get("ANTHROPIC_API_KEY"):
            self.client = anthropic.Anthropic()

    @property
    def available(self):
        return self.client is not None

    def judge(self, frame_bgr):
        """Return 'productive', 'lazy', or 'unsure'."""
        if self.client is None:
            return "unsure"

        ok, buf = cv2.imencode(".jpg", frame_bgr)
        if not ok:
            return "unsure"
        b64 = base64.standard_b64encode(buf.tobytes()).decode("utf-8")

        prompt = (
            f"Here is my definition of productive vs lazy:\n{self.definition}\n\n"
            "Look at this webcam frame of me and answer with EXACTLY one lowercase "
            "word: 'productive', 'lazy', or 'unsure'. No other text."
        )

        msg = self.client.messages.create(
            model=self.model,
            max_tokens=5,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        answer = msg.content[0].text.strip().lower()
        if "lazy" in answer:
            return "lazy"
        if "productive" in answer:
            return "productive"
        return "unsure"

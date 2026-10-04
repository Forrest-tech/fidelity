# -*- coding: utf-8 -*-
"""VLM 兜底：低置信 OCR 页的 AI 二次识别适配器（可插拔）。

用户决策（2026-10-04）：兜底用 WorkBuddy 内置模型，不引入第三方付费 API。
WorkBuddy 内置 LLM 是「应用级」云服务（wbapp + endpoint，OpenAI 兼容协议），
qa-platform 独立部署时通过 sites 发布即可获得端点；届时把 endpoint 填进
config.json 的 vlm 段即可启用，本模块零改动。

config.json 示例：
  "vlm": {
    "enabled": false,                  # true 后低置信页自动走 VLM
    "base_url": "https://<wbapp-endpoint>/v1",
    "api_key": "",                     # WorkBuddy 免密钥模式可留空
    "model": "<模型ID，需 supportsImages>"
  }

未启用/调用失败时的行为（优雅降级）：返回 None → 上层保持「低置信+人工复核」
标记，绝不因兜底不可用而丢数据或阻塞流程。
"""
import os
import json
import base64

# 单页图片发给 VLM 的体积上限（超过压缩）
_MAX_IMG_BYTES = 3 * 1024 * 1024
_TIMEOUT = 60


def _cfg():
    try:
        from .. import config
        raw = getattr(config, "RAW", None) or {}
        if isinstance(raw, dict) and isinstance(raw.get("vlm"), dict):
            return raw["vlm"]
    except Exception:
        pass
    # 直接读 config.json 兜底（独立运行/子进程场景）
    try:
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "..", "..", "data", "config.json")
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f).get("vlm", {})
    except Exception:
        return {}


def enabled() -> bool:
    c = _cfg()
    return bool(c.get("enabled") and c.get("base_url") and c.get("model"))


def _png_data_url(png: bytes) -> str:
    if len(png) > _MAX_IMG_BYTES:
        try:
            import io
            from PIL import Image
            img = Image.open(io.BytesIO(png))
            img.thumbnail((2000, 2000))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            png = buf.getvalue()
        except Exception:
            pass
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


_OCR_PROMPT = (
    "你是工程文档 OCR 专家。识别图片中的全部文字内容，输出纯文本，遵守：\n"
    "1. 保持原有阅读顺序与分行；2. 数字、单位、编号必须逐字符精确（如 25mm、DN100、AS 2419.1）\n"
    "3. 表格按行输出，单元格间用 ' | ' 分隔；4. 不要添加任何解释、标注或 markdown 符号。\n"
)


def ocr_page_vlm(png: bytes):
    """对单页 PNG 做 VLM 识别。返回 (text, conf or None)；不可用/失败返回 None。"""
    if not enabled():
        return None
    c = _cfg()
    try:
        import urllib.request
        body = json.dumps({
            "model": c["model"],
            "messages": [
                {"role": "user", "content": [
                    {"type": "text", "text": _OCR_PROMPT},
                    {"type": "image_url", "image_url": {"url": _png_data_url(png)}},
                ]},
            ],
            "temperature": 0,
        }).encode("utf-8")
        req = urllib.request.Request(
            c["base_url"].rstrip("/") + "/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     **({"Authorization": "Bearer " + c["api_key"]} if c.get("api_key") else {})})
        import urllib.error  # noqa: F401
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        txt = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return (txt or "").strip() or None
    except Exception:
        return None

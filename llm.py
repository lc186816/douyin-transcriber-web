"""OpenAI 兼容文本大模型调用与预置提示词。"""

import requests

from douyin import DouyinError

FIX_PROMPT = (
    "你是中文文字修正助手。下面是从语音识别得到的文字，可能存在：无标点、断句错误、"
    "同音字错误、语序混乱、口语化冗余。请将其修正为通顺、正确、符合书面语习惯的中文，"
    "保留原意与所有信息点，不要增删内容含义，不要添加解释。只输出修正后的文字：\n\n{text}"
)

MARKET_PROMPT = (
    "你是资深A股策略分析师。请基于以下两方面的信息，预测A股市场明日行情。\n\n"
    "一、今日大盘与板块行情数据：\n{market_data}\n\n"
    "二、近期抖音财经类视频文案（反映市场情绪与讨论热点）：\n{transcripts}\n\n"
    "请输出以下四个部分，每部分用标题开头：\n"
    "【大盘预测】明日上证指数及主要指数走势判断（含方向与幅度区间）\n"
    "【板块预测】明日可能领涨/领跌的板块\n"
    "【板块机会】值得关注的板块机会及逻辑\n"
    "【涨跌情绪】市场整体多空情绪判断（乐观/谨慎/悲观）\n\n"
    "基于数据理性分析，不要编造具体数字，不确定处明确说明。"
)

MARKET_PROMPT_NO_MARKET = (
    "你是资深A股策略分析师。请基于以下近期抖音财经类视频文案"
    "（反映市场情绪与讨论热点），预测A股市场明日行情。\n\n"
    "近期视频文案：\n{transcripts}\n\n"
    "请输出以下四个部分，每部分用标题开头：\n"
    "【大盘预测】明日上证指数及主要指数走势判断（含方向与幅度区间）\n"
    "【板块预测】明日可能领涨/领跌的板块\n"
    "【板块机会】值得关注的板块机会及逻辑\n"
    "【涨跌情绪】市场整体多空情绪判断（乐观/谨慎/悲观）\n\n"
    "本次分析未提供行情数据，请基于文案内容理性推断，不要编造具体数字，不确定处明确说明。"
)


def chat(cfg: dict, messages: list, temperature: float = 0.7) -> str:
    """调用 OpenAI 兼容 /chat/completions，返回回复文本。"""
    base_url = cfg.get("llm_base_url", "").rstrip("/")
    api_key = cfg.get("llm_api_key", "")
    model = cfg.get("llm_model", "")
    if not base_url or not api_key or not model:
        raise DouyinError("请先在设置中配置文本大模型（地址/Key/模型名）")
    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": messages, "temperature": temperature},
            timeout=300,
        )
    except Exception as e:
        raise DouyinError(f"文本大模型请求失败: {e}")
    if resp.status_code == 401:
        raise DouyinError("文本大模型 API Key 无效（401）")
    if resp.status_code != 200:
        raise DouyinError(f"文本大模型 API 错误 {resp.status_code}: {resp.text[:300]}")
    return resp.json()["choices"][0]["message"]["content"].strip()


def fix_text(cfg: dict, text: str) -> str:
    return chat(cfg, [
        {"role": "system", "content": "你只输出修正后的文字，不输出任何其他内容。"},
        {"role": "user", "content": FIX_PROMPT.format(text=text)},
    ], temperature=0.3)


def analyze_market(cfg: dict, transcripts: str,
                   market_data: str | None = None) -> str:
    if market_data:
        content = MARKET_PROMPT.format(market_data=market_data,
                                       transcripts=transcripts)
    else:
        content = MARKET_PROMPT_NO_MARKET.format(transcripts=transcripts)
    return chat(cfg, [
        {"role": "system", "content": "你是一位严谨的A股策略分析师。"},
        {"role": "user", "content": content},
    ])

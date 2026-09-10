"""
大模型服务层（外接 API，OpenAI 兼容协议）
=========================================

设计目标
--------
1. **可切换模型**：改 `AI_PROVIDER`（deepseek / openai / qwen / zhipu）即可换供应商，
   或显式给 `AI_BASE_URL` + `AI_MODEL` 接入任意 OpenAI 兼容服务。
2. **永不把异常抛给业务**：任何失败（未配置 / 超时 / 限流 / 网络断）统一返回 `None`，
   由调用方降级到规则文案。演示现场断网也不会白屏。
3. **控成本**：相同请求 60s 内命中缓存；`max_tokens` 封顶；重试次数受限。
4. **密钥安全**：只从环境变量读取，日志中绝不打印 key。

架构约定（重要）
----------------
大模型**不负责判断座位是否被占用**——那是传感器 + 规则的确定性职责。
本层只做两件事：把结构化事实**翻译成人话**、从历史数据里**发现模式**。
这样可避免模型幻觉编造座位状态。
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """LLM 调用异常（仅内部使用，不向业务层抛出）。"""


class LLMClient:
    """OpenAI 兼容协议的大模型客户端（带缓存 / 重试 / 降级）。

    典型用法::

        llm = get_llm()
        if llm.configured:
            text = llm.chat([{'role': 'user', 'content': '...'}])
        if text is None:
            text = rule_based_fallback()   # 降级
    """

    def __init__(
        self,
        base_url: str = '',
        api_key: str = '',
        model: str = '',
        timeout: int = 20,
        max_retries: int = 2,
        max_tokens: int = 600,
        temperature: float = 0.3,
        cache_ttl: int = 60,
        enabled: bool = True,
        provider: str = '',
    ) -> None:
        self.base_url = (base_url or '').rstrip('/')
        self.api_key = (api_key or '').strip()
        self.model = (model or '').strip()
        self.timeout = max(int(timeout or 20), 1)
        self.max_retries = max(int(max_retries or 0), 0)
        self.max_tokens = max(int(max_tokens or 600), 1)
        self.temperature = float(temperature if temperature is not None else 0.3)
        self.cache_ttl = max(int(cache_ttl or 0), 0)
        self.enabled = bool(enabled)
        self.provider = provider or 'custom'

        self._cache: Dict[str, tuple] = {}          # key -> (expire_ts, text)
        self._lock = threading.Lock()
        self._stats = {'calls': 0, 'hits': 0, 'errors': 0, 'fallbacks': 0}

    # ------------------------------------------------------------------ 状态
    @property
    def configured(self) -> bool:
        """是否具备调用条件（开关打开 + 三项配置齐全）。"""
        return bool(self.enabled and self.base_url and self.api_key and self.model)

    def status(self) -> Dict[str, Any]:
        """对外暴露的状态（**不含密钥**），用于管理面板展示。"""
        with self._lock:
            stats = dict(self._stats)
        return {
            'enabled': self.enabled,
            'configured': self.configured,
            'provider': self.provider,
            'model': self.model,
            'base_url': self.base_url,
            'api_key_set': bool(self.api_key),   # 只报是否设置，绝不返回值
            'timeout': self.timeout,
            'max_tokens': self.max_tokens,
            'cache_ttl': self.cache_ttl,
            'stats': stats,
        }

    def reset_stats(self) -> None:
        with self._lock:
            self._stats = {'calls': 0, 'hits': 0, 'errors': 0, 'fallbacks': 0}

    # ------------------------------------------------------------------ 缓存
    @staticmethod
    def _make_cache_key(messages: List[Dict[str, str]], model: str,
                        max_tokens: int, temperature: float) -> str:
        payload = json.dumps(
            {'m': messages, 'model': model, 'mt': max_tokens, 'tp': temperature},
            ensure_ascii=False, sort_keys=True,
        )
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()

    def _cache_get(self, key: str) -> Optional[str]:
        if self.cache_ttl <= 0:
            return None
        now = time.time()
        with self._lock:
            item = self._cache.get(key)
            if not item:
                return None
            expire_ts, text = item
            if expire_ts < now:
                self._cache.pop(key, None)
                return None
            self._stats['hits'] += 1
            return text

    def _cache_put(self, key: str, text: str) -> None:
        if self.cache_ttl <= 0:
            return
        with self._lock:
            # 顺手清理过期项，避免内存无限增长
            now = time.time()
            for k in [k for k, (exp, _) in self._cache.items() if exp < now]:
                self._cache.pop(k, None)
            self._cache[key] = (now + self.cache_ttl, text)

    def clear_cache(self) -> int:
        with self._lock:
            n = len(self._cache)
            self._cache.clear()
        return n

    # ------------------------------------------------------------------ 调用
    def chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        use_cache: bool = True,
    ) -> Optional[str]:
        """发起一次对话补全。

        Args:
            messages: OpenAI 格式消息列表，如 ``[{'role':'user','content':'...'}]``。
            max_tokens: 覆盖默认生成上限。
            temperature: 覆盖默认温度。
            use_cache: 是否允许命中缓存（实时性要求高的场景可关）。

        Returns:
            模型回复文本；**任何失败都返回 None**（调用方需自行降级）。
        """
        if not self.configured:
            with self._lock:
                self._stats['fallbacks'] += 1
            logger.debug('LLM 未配置或已禁用，跳过调用')
            return None

        mt = int(max_tokens if max_tokens is not None else self.max_tokens)
        tp = float(temperature if temperature is not None else self.temperature)
        cache_key = self._make_cache_key(messages, self.model, mt, tp)

        if use_cache:
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached

        url = f'{self.base_url}/chat/completions'
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }
        body = {
            'model': self.model,
            'messages': messages,
            'max_tokens': mt,
            'temperature': tp,
            'stream': False,
        }

        attempts = self.max_retries + 1
        last_err: Optional[str] = None
        for attempt in range(attempts):
            try:
                with self._lock:
                    self._stats['calls'] += 1
                resp = requests.post(url, headers=headers, json=body, timeout=self.timeout)

                if resp.status_code == 200:
                    text = self._extract_text(resp.json())
                    if not text:
                        last_err = '响应内容为空'
                    else:
                        if use_cache:
                            self._cache_put(cache_key, text)
                        return text
                elif resp.status_code in (401, 403):
                    # 鉴权失败：重试无意义，直接放弃
                    last_err = f'鉴权失败 HTTP {resp.status_code}（请检查 AI_API_KEY）'
                    break
                elif resp.status_code == 429:
                    last_err = '触发限流 HTTP 429'
                elif resp.status_code >= 500:
                    last_err = f'服务端错误 HTTP {resp.status_code}'
                else:
                    last_err = f'HTTP {resp.status_code}: {resp.text[:200]}'
            except requests.Timeout:
                last_err = f'请求超时（{self.timeout}s）'
            except requests.RequestException as exc:
                last_err = f'网络异常: {exc}'
            except (ValueError, KeyError, TypeError) as exc:
                last_err = f'响应解析失败: {exc}'

            if attempt < attempts - 1:
                time.sleep(min(2 ** attempt, 4))   # 退避重试

        with self._lock:
            self._stats['errors'] += 1
            self._stats['fallbacks'] += 1
        logger.warning('LLM 调用失败，将降级为规则文案：%s', last_err)
        return None

    @staticmethod
    def _extract_text(data: Dict[str, Any]) -> str:
        """从 OpenAI 兼容响应中取出文本（兼容 reasoning 系列的空 content）。"""
        choices = data.get('choices') or []
        if not choices:
            return ''
        message = choices[0].get('message') or {}
        content = message.get('content')
        if isinstance(content, str):
            return content.strip()
        # 部分模型返回分段 content
        if isinstance(content, list):
            parts = [seg.get('text', '') for seg in content if isinstance(seg, dict)]
            return ''.join(parts).strip()
        return ''

    # ------------------------------------------------------------------ 探活
    def test_connection(self) -> Dict[str, Any]:
        """连通性自检，供管理面板「测试 AI」按钮调用。"""
        if not self.configured:
            return {'ok': False, 'reason': '未配置（缺少 base_url / api_key / model，或 AI 已禁用）'}
        started = time.time()
        text = self.chat(
            [{'role': 'user', 'content': '回复两个字：正常'}],
            max_tokens=16, use_cache=False,
        )
        elapsed = round(time.time() - started, 2)
        if text is None:
            return {'ok': False, 'reason': '调用失败（详见服务端日志）', 'elapsed': elapsed}
        return {'ok': True, 'reply': text, 'elapsed': elapsed,
                'model': self.model, 'provider': self.provider}


# ---------------------------------------------------------------------- 单例
_llm_singleton: Optional[LLMClient] = None
_singleton_lock = threading.Lock()


def build_llm_from_config() -> LLMClient:
    """按 `config.Config` 构造客户端（配置改动后可重建以生效）。"""
    from config import Config
    return LLMClient(
        base_url=getattr(Config, 'AI_BASE_URL', ''),
        api_key=getattr(Config, 'AI_API_KEY', ''),
        model=getattr(Config, 'AI_MODEL', ''),
        timeout=getattr(Config, 'AI_TIMEOUT', 20),
        max_retries=getattr(Config, 'AI_MAX_RETRIES', 2),
        max_tokens=getattr(Config, 'AI_MAX_TOKENS', 600),
        temperature=getattr(Config, 'AI_TEMPERATURE', 0.3),
        cache_ttl=getattr(Config, 'AI_CACHE_TTL', 60),
        enabled=getattr(Config, 'AI_ENABLED', True),
        provider=getattr(Config, 'AI_PROVIDER', 'custom'),
    )


def get_llm() -> LLMClient:
    """获取全局 LLM 客户端单例。"""
    global _llm_singleton
    if _llm_singleton is None:
        with _singleton_lock:
            if _llm_singleton is None:
                _llm_singleton = build_llm_from_config()
    return _llm_singleton


def reload_llm() -> LLMClient:
    """重建全局客户端（配置变更后调用）。"""
    global _llm_singleton
    with _singleton_lock:
        _llm_singleton = build_llm_from_config()
    return _llm_singleton

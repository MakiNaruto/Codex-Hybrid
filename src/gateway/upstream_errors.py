"""Shared upstream error classification and bounded local diagnostic messages."""
import json
import re


ERROR_MESSAGES = {
    'UPSTREAM_REASONING_EFFORT_UNSUPPORTED': '当前模型不支持所选思考强度，请选择模型支持的档位。',
    'UPSTREAM_AUTHENTICATION_FAILED': '上游身份验证失败，请检查 API Key。',
    'UPSTREAM_PERMISSION_DENIED': '上游拒绝访问，请检查模型权限。',
    'UPSTREAM_QUOTA_EXCEEDED': '上游额度不足，请检查账户余额或套餐额度。',
    'UPSTREAM_RATE_LIMITED': '上游请求限流，请稍后重试。',
    'UPSTREAM_MODEL_NOT_FOUND': '上游找不到请求的模型，请检查模型 ID。',
    'UPSTREAM_CONTEXT_LIMIT_EXCEEDED': '请求超出模型上下文限制，请缩短对话。',
    'UPSTREAM_INVALID_REQUEST': '上游拒绝了请求参数，请查看错误详情。',
    'UPSTREAM_UNAVAILABLE': '上游服务暂时不可用，请稍后重试。',
    'UPSTREAM_STREAM_ERROR': '上游响应流报告错误，请查看错误详情。',
}


def redact_text(value, secrets=()):
    for secret in secrets:
        if isinstance(secret, str) and secret:
            value = value.replace(secret, '[已隐藏]')
    value = re.sub(r'(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*', 'Bearer [已隐藏]', value)
    value = re.sub(r'\bsk-[A-Za-z0-9_-]+', '[已隐藏]', value)
    value = re.sub(r'(?i)((?:api[_-]?key|token|password|secret|authorization)["\s]*[:=]\s*["\s]*)'
                   r'[^\s,;"\'}]+', r'\1[已隐藏]', value)
    return re.sub(r'(https?://)[^/\s@]+@', r'\1[已隐藏]@', value)


def diagnostic(detail, status=None, secrets=()):
    """Classify raw provider errors before adapters discard the original message."""
    detail = detail if isinstance(detail, dict) else {}
    code = str(detail.get('code', '')).lower()
    kind = str(detail.get('type', '')).lower()
    message = detail.get('message')
    message = message if isinstance(message, str) else ''
    text = (code + ' ' + kind + ' ' + message).lower()
    effort_error = any(term in text for term in (
        'reasoning.effort', 'reasoning_effort', 'reasoning effort', '思考强度', '不支持关闭思考'))
    if effort_error and any(
            term in text for term in ('unsupported', 'not support', 'invalid', '不支持', '请使用')):
        category = 'UPSTREAM_REASONING_EFFORT_UNSUPPORTED'
    elif any(term in text for term in ('insufficient_quota', 'quota exceeded', '余额不足', '额度不足')):
        category = 'UPSTREAM_QUOTA_EXCEEDED'
    elif status == 401 or code == 'invalid_api_key' or kind == 'authentication_error':
        category = 'UPSTREAM_AUTHENTICATION_FAILED'
    elif status == 403 or code in {'permission_denied', 'access_denied'} or kind == 'permission_error':
        category = 'UPSTREAM_PERMISSION_DENIED'
    elif status == 429 or code == 'rate_limit_exceeded' or kind == 'rate_limit_error':
        category = 'UPSTREAM_RATE_LIMITED'
    elif code in {'model_not_found', 'model_not_exist'}:
        category = 'UPSTREAM_MODEL_NOT_FOUND'
    elif code in {'context_length_exceeded', 'context_window_exceeded'}:
        category = 'UPSTREAM_CONTEXT_LIMIT_EXCEEDED'
    elif status is not None and status >= 500:
        category = 'UPSTREAM_UNAVAILABLE'
    elif status in {400, 404, 422} or code in {'invalid_request', 'invalid_request_error'} or kind == 'invalid_request_error':
        category = 'UPSTREAM_INVALID_REQUEST'
    else:
        category = 'UPSTREAM_STREAM_ERROR'
    local = {}
    result = {'error_code': category}
    for key in ('type', 'code', 'param'):
        value = detail.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            local[key] = redact_text(str(value), secrets)[:180]
            if key != 'param':
                result['upstream_error_' + key] = local[key]
    if message:
        safe = redact_text(message, secrets)
        local['message'] = safe[:4096]
        # Runtime records have a 16 KiB serialized limit, including JSON's
        # Unicode escapes. Leave room for the request's remaining metadata.
        while len(json.dumps(local['message'])) > 8192:
            local['message'] = local['message'][:len(local['message']) // 2]
        if local['message'] != safe:
            local['message_truncated'] = True
    if local:
        result['upstream_error'] = local
    return result

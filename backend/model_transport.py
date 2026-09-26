"""Offline preflight and private HTTPS boundary; not wired to jobs or live CLI.

Local tokenizer estimates and frozen prices are not provider billing limits.
Live dispatch remains unintegrated; HTTP tests use mocks, never a real key.
"""

import hashlib
import http.client
import json
import ssl
import time

from backend.errors import ApiError
from backend.model_advice import build_request, RATES, PRICE_REFERENCE, MAX_REQUEST_BYTES, _unique_object
from backend.model_budget import estimate
from backend.model_tokens import estimate_input_tokens, INPUT_REFERENCE, TOKENIZER_PATH


CALL_LIMIT_MICROYUAN = 100_000
MAX_RESPONSE_BYTES = 262_144
SOCKET_TIMEOUT = 30
RESPONSE_DEADLINE = 60


def prepare_request(snapshot, *, tokenizer_path=TOKENIZER_PATH):
    """Estimate the chosen Flash request and quote a fixed 0.10 CNY reservation.

    Uses the reviewed local template, not a provider-certified input bound.
    A quote is NOT permission to send or an already-persisted reservation.
    """
    payload = build_request(snapshot, model='deepseek-flash')
    if payload is None:
        return None
    input_tokens = estimate_input_tokens(payload['messages'], tokenizer_path=tokenizer_path)
    if type(input_tokens) is not int or not 0 < input_tokens <= 1_000_000:
        raise ValueError('Expected a positive bounded token estimate')
    input_rate, output_rate = RATES[payload['model']]
    amount = estimate(input_tokens, payload['max_tokens'], input_rate, output_rate)
    if amount > CALL_LIMIT_MICROYUAN:
        raise ApiError(409, 'MODEL_CALL_LIMIT', '本次预计费用超过0.10元，拒绝发送')
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    return {'body': body, 'request_sha256': hashlib.sha256(body).hexdigest(),
        'estimated_microyuan': amount,
        'quote': {'model': payload['model'], 'price_reference': PRICE_REFERENCE,
            'input_tokens': input_tokens, 'max_output_tokens': payload['max_tokens'],
            'reservation_microyuan': CALL_LIMIT_MICROYUAN, 'input_reference': INPUT_REFERENCE,
            'input_rate': input_rate, 'output_rate': output_rate}}


def _invalid_constant(_value):
    raise ValueError('Non-JSON number')


def _post_json(body, api_key):
    """One private HTTPS POST; no redirects, proxy discovery, logging or retries.

    Caller must reserve the quote before dispatch and retain unknown usage on
    any failure. No production caller exists yet. Never log these arguments.
    """
    if not isinstance(body, bytes) or not 0 < len(body) <= MAX_REQUEST_BYTES:
        raise ValueError('Invalid model request size')
    if (not isinstance(api_key, str) or not api_key
            or any(not 33 <= ord(c) <= 126 or c in '\"\'' for c in api_key)):
        raise ValueError('Invalid model credential')
    connection = http.client.HTTPSConnection('api.deepseek.com', timeout=SOCKET_TIMEOUT,
        context=ssl.create_default_context())
    try:
        connection.connect()
        sock = connection.sock
        # ponytail: stdlib blocking DNS is outside this deadline; a job lease
        # must cover it when live jobs are implemented. TLS uses socket timeout.
        deadline = time.monotonic() + RESPONSE_DEADLINE

        def remaining_timeout():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            sock.settimeout(min(SOCKET_TIMEOUT, remaining))

        remaining_timeout()
        connection.request('POST', '/chat/completions', body=body,
            headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json',
                     'Accept': 'application/json', 'Accept-Encoding': 'identity'})
        remaining_timeout()
        response = connection.getresponse()
        if response.status != 200:
            code = {401: 'MODEL_AUTH_FAILED', 403: 'MODEL_AUTH_FAILED',
                    402: 'MODEL_BALANCE_REQUIRED', 429: 'MODEL_RATE_LIMIT'}.get(response.status, 'MODEL_HTTP_ERROR')
            raise ApiError(502, code, '模型服务请求未成功，未自动重试；费用需核对')
        if (response.getheader('Content-Type', '').split(';')[0].strip().lower() != 'application/json'
                or response.getheader('Content-Encoding', 'identity').strip().lower() != 'identity'):
            raise ApiError(502, 'MODEL_RESPONSE_INVALID', '模型响应格式无效，费用需核对')
        content_length = response.getheader('Content-Length')
        if content_length is not None:
            if not content_length.isascii() or not content_length.isdecimal() or len(content_length) > 10:
                raise ApiError(502, 'MODEL_RESPONSE_INVALID', '模型响应长度无效，费用需核对')
            if int(content_length) > MAX_RESPONSE_BYTES:
                raise ApiError(502, 'MODEL_RESPONSE_TOO_LARGE', '模型响应超出大小限制，费用需核对')
        data = bytearray()
        while True:
            remaining_timeout()
            chunk = response.read1(min(16_384, MAX_RESPONSE_BYTES + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > MAX_RESPONSE_BYTES:
                raise ApiError(502, 'MODEL_RESPONSE_TOO_LARGE', '模型响应超出大小限制，费用需核对')
        remaining_timeout()
        if content_length is not None and len(data) != int(content_length):
            raise ValueError('Truncated response')
        parsed = json.loads(data.decode('utf-8'), object_pairs_hook=_unique_object,
            parse_constant=_invalid_constant)
        if not isinstance(parsed, dict):
            raise ValueError('Expected an object')
        return parsed
    except TimeoutError:
        raise ApiError(504, 'MODEL_TIMEOUT', '模型请求超时，未自动重试；费用需核对') from None
    except (OSError, http.client.HTTPException):
        raise ApiError(502, 'MODEL_TRANSPORT_FAILED', '模型连接失败，未自动重试；费用需核对') from None
    except (ValueError, RecursionError):
        raise ApiError(502, 'MODEL_RESPONSE_INVALID', '模型响应无法解析，费用需核对') from None
    finally:
        connection.close()

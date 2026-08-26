"""NEIS 응답 상태 코드 분류.

코드표는 포털 문서 기준으로 채워두되, 코드가 바뀌거나 미등록 코드가 와도
메시지 본문으로 한 번 더 판정한다. 여기서 잘못 분류하면 사용자에게
엉뚱한 안내가 나가므로 방어적으로 처리한다.
"""

from __future__ import annotations

from enum import Enum


class ResultKind(Enum):
    OK = "ok"
    NO_DATA = "no_data"
    BAD_KEY = "bad_key"
    QUOTA = "quota"
    BAD_REQUEST = "bad_request"
    SERVER = "server"
    NETWORK = "network"
    UNKNOWN = "unknown"


#: 관찰된 NEIS RESULT.CODE → 분류.
#: 실제 응답으로 확인되는 대로 갱신한다.
CODE_MAP: dict[str, ResultKind] = {
    "INFO-000": ResultKind.OK,
    "INFO-200": ResultKind.NO_DATA,
    "INFO-300": ResultKind.BAD_KEY,  # 관리자에 의해 인증키 사용이 제한됨
    "ERROR-290": ResultKind.BAD_KEY,  # 인증키가 유효하지 않음
    "ERROR-300": ResultKind.BAD_REQUEST,  # 필수 값 누락
    "ERROR-310": ResultKind.BAD_REQUEST,  # 서비스를 찾을 수 없음
    "ERROR-333": ResultKind.BAD_REQUEST,  # 요청 위치 값 타입 오류
    "ERROR-336": ResultKind.BAD_REQUEST,  # 요청 건수 초과
    "ERROR-337": ResultKind.QUOTA,  # 일일 트래픽 제한 초과
    "ERROR-500": ResultKind.SERVER,
    "ERROR-600": ResultKind.SERVER,
    "ERROR-601": ResultKind.SERVER,
}

_MESSAGE_HINTS: tuple[tuple[tuple[str, ...], ResultKind], ...] = (
    (("인증키", "인증 키", "authentication key"), ResultKind.BAD_KEY),
    (("트래픽", "traffic", "제한을 넘은"), ResultKind.QUOTA),
    (("데이터가 없", "no data"), ResultKind.NO_DATA),
    (("필수", "누락", "유효하지 않"), ResultKind.BAD_REQUEST),
)

USER_MESSAGES: dict[ResultKind, str] = {
    ResultKind.OK: "정상적으로 조회했습니다.",
    ResultKind.NO_DATA: "해당하는 데이터가 없습니다.",
    ResultKind.BAD_KEY: "NEIS 이용이 제한되었습니다. 잠시 후 다시 시도해 주세요.",
    ResultKind.QUOTA: "오늘 호출 한도를 초과했습니다. 내일 다시 시도해 주세요.",
    ResultKind.BAD_REQUEST: "요청이 올바르지 않습니다.",
    ResultKind.SERVER: "NEIS 서버에 문제가 있습니다. 잠시 후 다시 시도해 주세요.",
    ResultKind.NETWORK: "서버에 연결할 수 없습니다. 네트워크를 확인해 주세요.",
    ResultKind.UNKNOWN: "확인하지 못했습니다.",
}


def classify(code: str, message: str = "") -> ResultKind:
    code = (code or "").strip().upper()
    if code in CODE_MAP:
        return CODE_MAP[code]

    lowered = (message or "").lower()
    for needles, kind in _MESSAGE_HINTS:
        if any(needle.lower() in lowered for needle in needles):
            return kind

    if code.startswith("INFO"):
        return ResultKind.OK
    return ResultKind.UNKNOWN


def user_message(kind: ResultKind, code: str = "", message: str = "") -> str:
    """사용자에게 보여줄 문구. 알 수 없는 경우에만 원본 코드를 덧붙인다."""
    text = USER_MESSAGES.get(kind, USER_MESSAGES[ResultKind.UNKNOWN])
    if kind is ResultKind.UNKNOWN and (code or message):
        detail = " ".join(part for part in (code, message) if part).strip()
        return f"{text} ({detail})"
    return text

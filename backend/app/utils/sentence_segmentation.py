import re


_TRAILING_CLOSERS = set('"\'”’)]}〉》」』')
_SENTENCE_ENDERS = set(".?!。？！")


def split_response_sentences(text: str) -> list[str]:
    """
    사용자에게 말할 최종 응답을 한국어 자막/TTS용 문장 단위로 나눈다.

    숫자, 가격, 소수점 안의 마침표는 문장 경계로 보지 않고, 줄바꿈은
    문장 경계로 취급한다.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t\f\v]+", " ", normalized)
    normalized = re.sub(r"\n+", "\n", normalized).strip()
    if not normalized:
        return []

    sentences: list[str] = []
    start = 0
    index = 0
    length = len(normalized)

    while index < length:
        char = normalized[index]
        if char == "\n" or _is_sentence_boundary(normalized, index):
            end = index + 1
            while end < length and normalized[end] in _TRAILING_CLOSERS:
                end += 1
            _append_sentence(sentences, normalized[start:end])
            start = end
            while start < length and normalized[start].isspace():
                start += 1
            index = start
            continue
        index += 1

    _append_sentence(sentences, normalized[start:])
    return sentences


def _is_sentence_boundary(text: str, index: int) -> bool:
    char = text[index]
    if char not in _SENTENCE_ENDERS:
        return False

    if char == "." and _is_between_digits(text, index):
        return False

    next_index = index + 1
    if next_index >= len(text):
        return True

    next_char = text[next_index]
    if next_char.isspace() or next_char in _TRAILING_CLOSERS:
        return True

    return char in "?!？！"


def _is_between_digits(text: str, index: int) -> bool:
    previous_char = text[index - 1] if index > 0 else ""
    next_char = text[index + 1] if index + 1 < len(text) else ""
    return previous_char.isdigit() and next_char.isdigit()


def _append_sentence(sentences: list[str], raw_sentence: str) -> None:
    sentence = raw_sentence.strip()
    if sentence:
        sentences.append(sentence)

"""Fit scenario_main portrait lines to 15 12x12 cells without last-word shuffle."""
from __future__ import annotations

from typing import Any

MAX_DIALOGUE_CELLS = 15
BAD_START = (
    "은 ",
    "는 ",
    "이 ",
    "가 ",
    "을 ",
    "를 ",
    "의 ",
    "에 ",
    "도 ",
    "만 ",
    "과 ",
    "와 ",
    "랑 ",
    "께 ",
    "이다",
    "것이다",
    "따위",
    "따위가",
    "건 ",
    "걸 ",
    "것은 ",
    "거냐",
    "자가 ",
    "와서 ",
    "수 ",
)
MOD_END = ("최대", "최소", "최종", "자세", "완전", "절대", "서로", "아주", "너무", " 수", "내", "것")
REPLACEMENTS = [
    ("쓰러뜨릴 수 있을 거라 생각하지 마라", "쓰러뜨릴 생각 마라"),
    ("쓰러뜨릴 수 있을 거라 생각하지 마", "쓰러뜨릴 생각 마"),
    ("살아서 돌아갈 수 있을 거라 생각하지 마라", "살아 돌아갈 생각 마라"),
    ("살아서 돌아갈 수 있을 거라 생각하지 마", "살아 돌아갈 생각 마"),
    ("돌아갈 수 있을 거라 생각하지 마라", "돌아갈 생각 마라"),
    ("돌아갈 수 있을 거라 생각하지 마", "돌아갈 생각 마"),
    ("도망칠 수 있을 거라 생각하지 마라", "도망칠 생각 마라"),
    ("도망칠 수 있을 거라 생각하지 마", "도망칠 생각 마"),
    ("쓰러뜨릴 수 있을 것 같으냐", "쓰러뜨릴 것 같으냐"),
    ("사람의 목숨을 소중히 하지 않는 사람과는", "목숨을 안 아끼는 자와는"),
    ("무엇을 위해 누구와 싸우는지", "누구와 왜 싸우는지"),
    ("것 같으냐", "것 같냐"),
]

# Visible-line rewrites for rows the auto splitter cannot fit grammatically.
MANUAL: dict[str, list[str]] = {
    "GGA-SCENARIO-001F5FA8": ["서로 찔러 쓰러져도……!"],
    "GGA-SCENARIO-001F6664": ["이렇게 된 이상", "최대 출력으로 날려 버린다!"],
    "GGA-SCENARIO-001F669C": ["너희 따위의 힘으로", "아프사라스를 쓰러뜨릴까보냐！"],
    "GGA-SCENARIO-001F6764": ["안 쓰러뜨리면 쓰러진다……"],
    "GGA-SCENARIO-001F6E24": ["포착했다! 해낼 수 있어!"],
    "GGA-SCENARIO-001F78F4": ["죽기 싫으면 물러나라!"],
    "GGA-SCENARIO-001F7984": ["원한으로 싸우는 자에게", "이 몸은 쓰러지지 않는다！"],
    "GGA-SCENARIO-001F7A0C": ["얼마나 시시한지……", "금수일촉이란 이런 거다！"],
    "GGA-SCENARIO-001F7AAC": ["조국에 바친 이 목숨!", "포로의 치욕은 받지 않겠다!"],
    "GGA-SCENARIO-001F962C": ["전장에서 망설일 것 같냐！"],
    "GGA-SCENARIO-001FA5F8": ["어떻게든 후퇴하는 거다！"],
    "GGA-SCENARIO-001FAE54": ["성능이 너무 다르다아아！"],
    "GGA-SCENARIO-001FB620": ["그 기체는 안 어울려……"],
    "GGA-SCENARIO-001FB6D4": ["너에겐 미래를 못 말해……"],
    "GGA-SCENARIO-001FB85C": ["그렇게 쉽게 죽을 것 같냐!"],
    "GGA-SCENARIO-001FC52C": ["불쌍하지만 직격을 먹인다！"],
    "GGA-SCENARIO-001FC634": ["서로 죽이며 즐기냐?", "……그런 녀석은!"],
    "GGA-SCENARIO-001FC79C": ["너는 싸움의 근원이다!", "살려 둘 수 없어!"],
    "GGA-SCENARIO-001FC7E8": ["암흑으로 떨어져라아아！！"],
    "GGA-SCENARIO-001FC8A8": ["Z는 사람 의지를 흡수해", "힘으로 만드는 MS다!"],
    "GGA-SCENARIO-001FC9D8": ["우리는……", "서로 이해할지도 몰라!"],
    "GGA-SCENARIO-001FD82C": ["너희 따위에게 세계를", "마음대로 둘 것 같냐아！"],
    "GGA-SCENARIO-001FE6CC": ["피 안 묻히는 살인으로는", "아픔을 모르는 모양이군……"],
    "GGA-SCENARIO-00200548": ["그렇게 나오는군, 그렇다면!"],
    "GGA-SCENARIO-002006F8": ["지금 나에겐 망설임 없다！"],
    "GGA-SCENARIO-002007A0": ["이 몸이 산산이 부서져도!"],
    "GGA-SCENARIO-00200914": ["내가 쓰러뜨릴 적은……", "싸움의 불길을 번지는 자다！"],
    "GGA-SCENARIO-00200D34": ["쓸데없는 저항 마십시오!"],
    "GGA-SCENARIO-00201334": ["싸우면 사람이 죽는다……"],
    "GGA-SCENARIO-00201A48": ["……안이하군!", "그 무기로 날 못 쓰러뜨려!"],
    "GGA-SCENARIO-00202178": ["솜씨는 나쁘지 않군!"],
    "GGA-SCENARIO-00202744": ["생명의 고동을 느낀다！"],
    "GGA-SCENARIO-002033D8": ["인정하고 싶지 않다……", "젊음으로 인한 과오라는 것을"],
    "GGA-SCENARIO-00203A04": ["세계가 우리를 묵살하니까", "우린 세계를 멸하는 것이다!"],
    "GGA-SCENARIO-002040EC": ["오래 버티진 못하나……"],
    "GGA-SCENARIO-0020436C": ["거봐라! 이게 무모 아니면", "뭐가 무모하다는 거야!"],
    "GGA-SCENARIO-00204C90": ["싸우는 방법은 있을 거야!"],
    "GGA-SCENARIO-00204F14": ["싸우는 방법은 있을 거야!"],
    "GGA-SCENARIO-00204F8C": ["연방을 위해서가 아니야……", "동료를 위해서라면 싸운다!"],
    "GGA-SCENARIO-00205180": ["싸우는 방법은 있을 거야!"],
    "GGA-SCENARIO-00205198": ["싸우는 방법은 있을 거야!"],
    "GGA-SCENARIO-00205A14": ["백랑이면 전력으로 도망쳐라", "……그게 최선의 선택이다!"],
    "GGA-SCENARIO-00205A80": ["나에게 져도 부끄럽지 않다", "……당연한 결과니까！"],
    "GGA-SCENARIO-00205AC0": ["내가 백랑인 이유……", "몸으로 알게 해 주지!"],
    "GGA-SCENARIO-00206338": ["쓸데없는 저항 마십시오!"],
    "GGA-SCENARIO-00206398": ["이 무기로 어디까지 싸울지", "문제는 나 자신이군……"],
    "GGA-SCENARIO-002063D8": ["싸움에 미의식 따윈 없다！"],
    "GGA-SCENARIO-002064B8": ["……좋은 공세다!", "그것으로는 날 못 쓰러뜨려!"],
    "GGA-SCENARIO-00206DA4": ["너 따위가 이 나를", "쓰러뜨릴 리 없잖아？"],
    "GGA-SCENARIO-002070DC": ["할 수 있을 것 같진 않지만", "……할 수밖에 없네요"],
    "GGA-SCENARIO-002088F8": ["주제 파악 못 하는 놈이!"],
    "GGA-SCENARIO-00208990": ["물러나는 것도 병법……", "이 승부, 맡기겠다！"],
    "GGA-SCENARIO-002089D8": ["안일하다! 네놈의 공격 따위", "이 늙은이에겐 안 통해!"],
    "GGA-SCENARIO-00208BD4": ["네 피도 헛되이 않겠다", "……얌전히 입 다물어 다오"],
    "GGA-SCENARIO-00208C18": ["네 피도 헛되이 않겠다", "……얌전히 입 다물어 다오"],
    "GGA-SCENARIO-0020986C": ["그런 기술로는 나를", "쓰러뜨리기엔…… 무리！"],
    "GGA-SCENARIO-0020A048": ["더 이상 저항은 무의미하다！", "순순히 투항해라！"],
    "GGA-SCENARIO-0020A7E0": ["나한텐 도망칠 수 없다!!"],
    "GGA-SCENARIO-0020AEB8": ["범속한 것들아, 사라져라!!"],
    "GGA-SCENARIO-0020AF54": ["나는 마리온을 넘어섰다！", "네놈 따위……！"],
    "GGA-SCENARIO-0020B05C": ["쓸데없이 발버둥 치기는!"],
    "GGA-SCENARIO-0020B958": ["그렇게 나오는군, 하지만!!"],
    "GGA-SCENARIO-0020BC34": ["안일함이 목숨을 앗아간다!"],
    "GGA-SCENARIO-0020C8B0": ["여기서 돌아가다니……", "…용납되지 않아……！"],
    "GGA-SCENARIO-0020CE74": ["그런 공격, 맞을 리 있냐!"],
    "GGA-SCENARIO-0020D050": ["놓치지 않는다고 했다!!"],
    "GGA-SCENARIO-0020D310": ["자, 이걸 어쩔 테냐!?"],
    "GGA-SCENARIO-0020D434": ["이 바쿠를 따라오다니……", "과연, 대단하군!"],
    "GGA-SCENARIO-0020DCD4": ["왜 이렇게 되는 거야!?"],
    "GGA-SCENARIO-0020DD8C": ["큰일이다, 못 도망친다！！"],
    "GGA-SCENARIO-0020DF44": ["작전 실수는 죽음이다……", "이대로는 죽을 수 없어!"],
    "GGA-SCENARIO-0020DF78": ["좌측 추진기 손상이군！"],
    "GGA-SCENARIO-0020E898": ["추력 더욱 저하되었습니다！", "전투 속도를 못 유지합니다！"],
    "GGA-SCENARIO-0020F874": ["결국 피로 물든 숙명……", "벗어나려 하진 않는다！！"],
    "GGA-SCENARIO-0020F98C": ["죽지 않을 정도면 충분해!!"],
    "GGA-SCENARIO-0020FA1C": ["그렇게 나오는군, 그렇다면!"],
    "GGA-SCENARIO-0020FE8C": ["먼저 관에 들 쪽은 어디일까", "……그래, 적군 양반이여！！"],
    "GGA-SCENARIO-00210A1C": ["힘만으론 못 이긴다고", "말했을 텐데?"],
    "GGA-SCENARIO-002114B8": ["전쟁을 끝내기 위해 싸운다", "……그렇게 믿을 수밖에!"],
    "GGA-SCENARIO-00212144": ["그렇게 나올 줄 알았어！"],
    "GGA-SCENARIO-0021287C": ["죽지 않을 정도면 충분해!!"],
    "GGA-SCENARIO-00212D0C": ["안 싸우면 못 지키니까", "싸우는 거다！"],
    "GGA-SCENARIO-002146A8": ["안 치면 다음에 당하는 건", "자기일지도 모른다？"],
    "GGA-SCENARIO-00214730": ["예상 이상의 전력이다……", "물러날 타이밍 놓치지 마라！"],
    "GGA-SCENARIO-00214A30": ["그건 용기가 아니다", "……단순한 무모함이다！"],
    "GGA-SCENARIO-00214A54": ["네놈으론 상대가 안 된다!!"],
    "GGA-SCENARIO-00214A6C": ["네놈으론 상대가 안 된다!!"],
    "GGA-SCENARIO-0021546C": ["이 람바 랄이……", "싸움 속에서 싸움을 잊었다！"],
    "GGA-SCENARIO-00215B80": ["이젠 내 목숨만이 아니야", "그러니까, 죽을 수 없어!"],
    "GGA-SCENARIO-002178F0": ["손 안 대고 보기만 하다니", "할 수 있을 것 같냐！"],
    "GGA-SCENARIO-00218694": ["남김없이 재로 만들어 주마！"],
    "GGA-SCENARIO-00219148": ["서로 찔러 쓰러져도……!"],
    "GGA-SCENARIO-002191F4": ["이미 목숨은 버렸다……", "이제 와 무서울 것 없다！！"],
    "GGA-SCENARIO-002191AC": ["대위의 원수를 갚을 때까지！"],
    "GGA-SCENARIO-00219924": ["색적 경계, 게을리 마라！"],
    "GGA-SCENARIO-0021995C": ["……스친 상처일 뿐이다!", "당황 말고 각자 대응하라!"],
    "GGA-SCENARIO-0021AC74": ["이 리브라가 침몰한다고?", "그럴 리가……!!"],
    "GGA-SCENARIO-0021AC98": ["얼마나 형편없는 솜씨냐！", "대체 어디를 노리는 거냐？"],
    "GGA-SCENARIO-0021B56C": ["죽음의 바다에 가라앉아라！"],
    "GGA-SCENARIO-0021BA44": ["사정권에 적이 들어왔습니다！"],
    "GGA-SCENARIO-0021D080": ["스페이스노이드의 독립을", "쟁취하기 위해서라도！！"],
}


def visible_pairs(segments: list[str]) -> list[tuple[int, str]]:
    return [(index, text) for index, text in enumerate(segments) if str(text).strip()]


def collapse_at(text: str) -> str:
    result = text
    while len(result) > MAX_DIALOGUE_CELLS and result.endswith("＠"):
        result = result[:-1]
    return result


def apply_replacements(text: str) -> str:
    result = collapse_at(text)
    for old, new in REPLACEMENTS:
        result = result.replace(old, new)
    return result


def ok_right(text: str) -> bool:
    return not any(text.startswith(prefix) for prefix in BAD_START)


def ok_left(text: str) -> bool:
    return not any(text.endswith(suffix) for suffix in MOD_END)


def words_of(text: str) -> list[str]:
    return [part for part in text.split(" ") if part]


def join_words(parts: list[str]) -> str:
    return " ".join(parts)


def score_split(left: str, right: str) -> int:
    score = 0
    if left[-1] in "…！!？?":
        score += 10
    score -= abs(len(left) - len(right))
    return score


def split_words(parts: list[str]) -> tuple[str, str] | None:
    best: tuple[int, str, str] | None = None
    for index in range(1, len(parts)):
        left = join_words(parts[:index])
        right = join_words(parts[index:])
        if not left or not right:
            continue
        if len(left) > MAX_DIALOGUE_CELLS or len(right) > MAX_DIALOGUE_CELLS:
            continue
        if not ok_right(right) or not ok_left(left):
            continue
        current = (score_split(left, right), left, right)
        if best is None or current > best:
            best = current
    if best is None:
        return None
    return best[1], best[2]


def directional_move(line1: str, line2: str) -> tuple[str, str] | None:
    words1 = words_of(line1)
    words2 = words_of(line2)
    cands: list[tuple[int, str, str]] = []
    if len(line1) <= MAX_DIALOGUE_CELLS < len(line2):
        for index in range(1, len(words2)):
            left = join_words(words1 + words2[:index])
            right = join_words(words2[index:])
            if len(left) <= MAX_DIALOGUE_CELLS and len(right) <= MAX_DIALOGUE_CELLS and ok_right(right) and ok_left(left):
                cands.append((score_split(left, right), left, right))
    if len(line2) <= MAX_DIALOGUE_CELLS < len(line1):
        for index in range(1, len(words1)):
            left = join_words(words1[:index])
            right = join_words(words1[index:] + words2)
            if len(left) <= MAX_DIALOGUE_CELLS and len(right) <= MAX_DIALOGUE_CELLS and ok_right(right) and ok_left(left):
                cands.append((score_split(left, right), left, right))
    if not cands:
        return None
    cands.sort(reverse=True)
    return cands[0][1], cands[0][2]


def fit_visible_lines(record_id: str, lines: list[str]) -> tuple[list[str], str]:
    if record_id in MANUAL:
        fitted = list(MANUAL[record_id])
        if len(fitted) != len(lines):
            raise ValueError(f"{record_id} manual line count {len(fitted)} != {len(lines)}")
        if any(len(line) > MAX_DIALOGUE_CELLS for line in fitted):
            raise ValueError(f"{record_id} manual line exceeds 15: {fitted}")
        return fitted, "manual"
    shortened = [apply_replacements(line) for line in lines]
    if all(len(line) <= MAX_DIALOGUE_CELLS for line in shortened):
        return shortened, "shorten"
    if len(shortened) == 2:
        moved = directional_move(shortened[0], shortened[1])
        if moved:
            return [moved[0], moved[1]], "redistribute"
        split = split_words(words_of(shortened[0]) + words_of(shortened[1]))
        if split:
            return [split[0], split[1]], "redistribute"
    raise ValueError(f"{record_id} cannot fit: {shortened}")


def apply_to_segments(record_id: str, segments: list[str]) -> tuple[list[str], str] | None:
    pairs = visible_pairs(segments)
    if not pairs:
        return None
    lines = [text for _index, text in pairs]
    if max(len(line) for line in lines) <= MAX_DIALOGUE_CELLS:
        return None
    fitted, method = fit_visible_lines(record_id, lines)
    updated = list(segments)
    for (index, _old), new in zip(pairs, fitted, strict=True):
        updated[index] = new
    return updated, method


def translation_ko_from_segments(segments: list[str]) -> str:
    return "\n".join(text for text in segments if str(text).strip())


def overlong_scenario_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in records:
        if row.get("source_scope") != "scenario_main":
            continue
        if row.get("translation_status") != "translated":
            continue
        if row.get("scope_status") == "alias":
            continue
        segments = [str(item) for item in (row.get("translation_segments") or [])]
        pairs = visible_pairs(segments)
        if not pairs:
            continue
        if max(len(text) for _index, text in pairs) <= MAX_DIALOGUE_CELLS:
            continue
        rows.append(row)
    return rows

"""Shared observable Korean aliases for CLIP and BM25; unknown words stay visible."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

PREPROCESS_VERSION = 'observable-alias-v1'
ALIASES = {
    '검은색': 'black', '검정색': 'black', '검정': 'black', '블랙': 'black',
    '흰색': 'white', '화이트': 'white', '하얀': 'white',
    '빨간색': 'red', '빨강': 'red', '레드': 'red', '파란색': 'blue',
    '파랑': 'blue', '블루': 'blue', '초록색': 'green', '초록': 'green',
    '그린': 'green', '노란색': 'yellow', '노랑': 'yellow', '옐로': 'yellow',
    '갈색': 'brown', '브라운': 'brown', '분홍색': 'pink', '핑크': 'pink',
    '폴로 셔츠': 'polo shirt', '티셔츠': 't-shirt', '셔츠': 'shirt',
    '블라우스': 'blouse', '스웨터': 'sweater', '가디건': 'cardigan',
    '니트 조끼': 'knitted vest', '후드티': 'hoodie', '맨투맨': 'sweatshirt',
    '청바지': 'jeans', '치노': 'chinos', '카고 바지': 'cargo pants',
    '데님 반바지': 'denim shorts', '버뮤다 반바지': 'bermuda shorts',
    '운동 반바지': 'athletic shorts', '미니 스커트': 'mini skirt',
    '플리츠 스커트': 'pleated skirt', '롱 스커트': 'long skirt',
    '트렌치 코트': 'trench coat', '롱 코트': 'long coat', '피코트': 'pea coat',
    '봄버 재킷': 'bomber jacket', '데님 재킷': 'denim jacket', '블레이저': 'blazer',
    '패딩 재킷': 'puffer jacket', '플리스 재킷': 'fleece jacket', '패딩 조끼': 'padded vest',
    '스니커즈': 'sneakers', '운동화': 'sneakers', '슬립온': 'slip-on shoes',
    '캔버스화': 'canvas shoes', '로퍼': 'loafers', '옥스퍼드화': 'oxford shoes',
    '구두': 'formal shoes', '하이힐': 'heels', '부츠': 'boots', '샌들': 'sandals',
    '등산화': 'hiking shoes', '백팩': 'backpack', '배낭': 'backpack',
    '토트백': 'tote bag', '크로스백': 'crossbody bag', '모자': 'hat',
    '볼캡': 'cap', '비니': 'beanie', '버킷햇': 'bucket hat',
    '스카프': 'scarf', '목도리': 'scarf', '벨트': 'belt', '장갑': 'gloves',
    '상의': 'tops', '하의': 'bottoms', '아우터': 'outerwear',
    '신발': 'footwear', '액세서리': 'accessories',
    '오버사이즈': 'oversized', '오버핏': 'oversized', '슬림핏': 'slim',
    '레귤러핏': 'regular', '릴랙스핏': 'relaxed',
}


@dataclass(frozen=True)
class NormalizedText:
    raw: str
    encoded: str
    applied_aliases: tuple[tuple[str, str], ...]
    unknown_terms: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def normalize_text(raw: str) -> NormalizedText:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError('text must be a nonempty string')
    applied = []
    pattern = '|'.join(re.escape(word) for word in sorted(ALIASES, key=len, reverse=True))

    def replace(match: re.Match) -> str:
        word = match.group(0)
        applied.append((word, ALIASES[word]))
        return ' ' + ALIASES[word] + ' '

    text = re.sub(pattern, replace, raw.casefold())
    unknown = tuple(sorted(set(re.findall('[가-힣]+', text))))
    return NormalizedText(raw, ' '.join(text.split()), tuple(applied), unknown)


def tokenize(raw: str) -> list[str]:
    return re.findall(r'[\w]+(?:-[\w]+)*', normalize_text(raw).encoded)

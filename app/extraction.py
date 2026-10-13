"""Versioned layout heuristics; candidates require human review before Question creation."""
import re

# Multiple numbering formats; position/order checks reduce false boundaries.
START = re.compile(r"^\s*(?:(\d{1,3})[.)．](?:\s|$)|(\d{1,3})\s*번(?:\s|[.:])|문항\s*(\d{1,3})(?:\s|[.:]))")


def number(text):
    match = START.match(text)
    return int(next(x for x in match.groups() if x)) if match else None


def page_text(page):
    """Detect separate numbered columns, otherwise retain pdfplumber reading order."""
    words = page.extract_words()
    anchors = [w for w in words if number(w['text'] + ' ') is not None]
    mid = page.width / 2
    left = [w for w in anchors if w['x0'] < mid - 15]
    right = [w for w in anchors if w['x0'] > mid + 5]
    if left and right:
        # Only split on a clear gutter: no word spanning the center.
        if not any(w['x0'] < mid < w['x1'] for w in words):
            return '\n'.join((page.crop((0, 0, mid, page.height)).extract_text() or '',
                              page.crop((mid, 0, page.width, page.height)).extract_text() or '')), True
    return page.extract_text() or '', False


def split_questions(pages):
    result, current, warnings = [], None, []
    for page_number, text in pages:
        for line in text.splitlines():
            n = number(line)
            # New numbered boundaries must advance; duplicates are flagged as uncertain.
            if n is not None and (current is None or n > current['question_number']):
                if current:
                    result.append(current)
                current = {'question_number': n, 'text': line, 'pages': [page_number]}
            elif current:
                current['text'] += '\n' + line
                if page_number not in current['pages']:
                    current['pages'].append(page_number)
                if n is not None:
                    warnings.append(f'{page_number}쪽: 번호 {n}의 경계가 모호하여 이전 문항에 포함했습니다.')
    if current:
        result.append(current)
    if not result and any(text.strip() for _, text in pages):
        result = [{'question_number': 1, 'text': '\n'.join(text for _, text in pages if text.strip()),
                   'pages': [p for p, text in pages if text.strip()]}]
        warnings.append('문항 번호를 찾지 못했습니다. 전체 텍스트를 임시 후보로 만들었습니다. 직접 분리해 주세요.')
    for i, item in enumerate(result):
        item['source_indexes'] = [i]
    return result, warnings

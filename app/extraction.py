"""Auditable, coordinate-aware exam boundaries. Human review remains required."""
import re
import unicodedata
from statistics import median

VERSION = 'pdfplumber-layout-v2'


def marker(text, allow_circled=False):
    text = text.lstrip().lstrip('\\').lstrip().replace('\u200b', '').replace('\ufeff', '')
    if not text:
        return None, None
    # Inspect before NFKC: circled choices must not become ordinary question numbers.
    if '\u2460' <= text[0] <= '\u2473':
        return (ord(text[0]) - 0x2460 + 1, 'circled') if allow_circled else (None, 'choice')
    text = unicodedata.normalize('NFKC', text)
    named = re.match(r'^문항\s*(\d{1,3})(?=\D|$)', text)
    if named and int(named[1]) > 0:
        return int(named[1]), 'explicit'
    match = re.match(r'^(?:문항\s*)?(\d{1,3})\s*(?:[.)](?!\d)|번)', text)
    if match and int(match[1]) > 0:
        return int(match[1]), 'explicit'
    if re.fullmatch(r'\d{1,3}', text) and int(text) > 0:
        return int(text), 'standalone'
    return None, None


def number(text, allow_circled=False):
    return marker(text, allow_circled)[0]


def _rows(words):
    rows = []
    for word in sorted(words, key=lambda w: (w['top'], w['x0'])):
        if not rows or abs(word['top'] - rows[-1][0]['top']) > 3:
            rows.append([word])
        else:
            rows[-1].append(word)
    return [sorted(row, key=lambda w: w['x0']) for row in rows]


def _gutter(rows, width):
    """Vote for a repeated wide central gap, permitting spanning headers."""
    gaps = []
    for row in rows:
        gaps.append([(a['x1'], b['x0']) for a, b in zip(row, row[1:])
                     if b['x0'] - a['x1'] >= width * .045])
    votes = []
    for step in range(35, 66):
        x = width * step / 100
        support = sum(any(a < x < b for a, b in row_gaps) for row_gaps in gaps)
        # Columns need not share baselines. Repeated starts on both sides and a
        # clear vertical band also identify staggered left/right paragraphs.
        left_starts = sum(row[0]['x0'] < width * .3 and row[-1]['x1'] < x for row in rows)
        right_starts = sum(row[0]['x0'] > max(x, width * .35) for row in rows)
        clear_band = sum(not any(w['x0'] < x + width * .015 and w['x1'] > x - width * .015 for w in row) for row in rows)
        if min(left_starts, right_starts) >= 2 and clear_band >= len(rows) * .7:
            support = max(support, left_starts + right_starts)
        crossings = sum(any(w['x0'] < x < w['x1'] for w in row) for row in rows)
        left = sum(any(w['x1'] <= x for w in row) for row in rows)
        right = sum(any(w['x0'] >= x for w in row) for row in rows)
        if support >= 2 and support >= len(rows) * .3 and min(left, right) >= 2 and crossings <= max(1, len(rows) * .2):
            votes.append((support - crossings, -abs(step - 50), x))
    return max(votes)[2] if votes else None


def analyze_page(page, column_mode='auto', allow_circled=False):
    words = page.extract_words(x_tolerance=2, y_tolerance=3)
    rows = _rows(words)
    gutter = _gutter(rows, page.width) if column_mode == 'auto' else (page.width / 2 if column_mode == 'two' else None)
    spans, columns = [], [[], []] if gutter else [[]]
    first_body = min((row[0]['top'] for row in rows if gutter and any(
        a['x1'] < gutter < b['x0'] and b['x0'] - a['x1'] >= page.width * .045
        for a, b in zip(row, row[1:]))), default=0)
    for row in rows:
        # Retain full-width headings once; they must not disable two-column reading.
        if gutter and row[0]['top'] < first_body and row[0]['x0'] < gutter < row[-1]['x1']:
            spans.append(row)
            continue
        for col in range(len(columns)):
            selected = [w for w in row if not gutter or ((w['x0'] + w['x1']) / 2 < gutter) == (col == 0)]
            if selected:
                columns[col].append(selected)
    lines = []
    for col, group in [(-1, spans), *enumerate(columns)]:
        anchors = [row[0]['x0'] for row in group if marker(' '.join(w['text'] for w in row), allow_circled)[0] is not None and row[0]['top'] <= page.height * .94]
        margin = min(anchors, default=min((row[0]['x0'] for row in group), default=0))
        height = median([w['bottom'] - w['top'] for row in group for w in row]) if group else 12
        for index, row in enumerate(group):
            text = ' '.join(w['text'] for w in row)
            n, kind = marker(text, allow_circled)
            x0, top = row[0]['x0'], min(w['top'] for w in row)
            accepted, reason = n is not None, '번호 형식 인식'
            if n is not None:
                if col == -1:
                    accepted, reason = False, '전체 폭 머리말'
                elif x0 > margin + max(12, height):
                    accepted, reason = False, '본문 내부 들여쓰기 번호'
                elif top > page.height * .94:
                    accepted, reason = False, '하단 페이지 번호 가능성'
                elif kind == 'standalone':
                    next_top = group[index + 1][0]['top'] if index + 1 < len(group) else page.height * 2
                    accepted = 0 < next_top - top <= max(40, height * 3)
                    reason = '독립 번호와 다음 본문 줄 연결' if accepted else '본문과 떨어진 독립 숫자'
                elif kind == 'circled':
                    previous_bottom = max(w['bottom'] for w in group[index - 1]) if index else -100
                    accepted = top - previous_bottom >= height * .7
                    reason = '원형 번호 모드·문단 간격 확인' if accepted else '선택지처럼 밀집된 원형 번호'
                else:
                    reason = '열 시작 좌표의 문항 번호'
            elif kind == 'choice':
                reason = '원형 선택지: 문항 번호 모드가 꺼져 있음'
            lines.append({'text': text, 'x0': round(x0, 2), 'top': round(top, 2), 'column': col,
                          'number': n, 'kind': kind, 'accepted': accepted, 'reason': reason})
    native = page.extract_text() or ''
    native_numbers = [number(line, allow_circled) for line in native.splitlines() if number(line, allow_circled) is not None]
    ordered_numbers = [line['number'] for line in lines if line['accepted']]
    return {'text': '\n'.join(line['text'] for line in lines), 'two_columns': gutter is not None,
            'gutter_x': gutter, 'native_text': native, 'word_count': len(words), 'char_count': len(page.chars),
            'native_number_order': native_numbers, 'layout_number_order': ordered_numbers,
            'reading_order_changed': native_numbers != ordered_numbers, 'lines': lines,
            'column_mode': column_mode, 'allow_circled': allow_circled}


def page_text(page):
    layout = analyze_page(page)
    return layout['text'], layout['two_columns']


def missing_numbers(candidates):
    numbers = {x['question_number'] for x in candidates if 0 < x['question_number'] <= 999}
    return [n for n in range(1, max(numbers, default=0)) if n not in numbers]


def gap_warnings(candidates):
    return [f'{n}번 문항 경계 누락 가능성: 원문과 출처 페이지를 확인해 주세요.' for n in missing_numbers(candidates)]


def split_questions(pages, layouts=None, allow_circled=False):
    result, current, warnings = [], None, []
    for page_number, text in pages:
        entries = layouts[page_number]['lines'] if layouts else [
            {'text': line, 'number': number(line, allow_circled), 'accepted': number(line, allow_circled) is not None}
            for line in text.splitlines()]
        for entry in entries:
            line = entry['text']
            n = entry['number'] if entry['accepted'] else None
            if n is not None and (current is None or n > current['question_number']):
                if current:
                    result.append(current)
                current = {'question_number': n, 'text': line, 'pages': [page_number]}
            elif current:
                current['text'] += '\n' + line
                if page_number not in current['pages']:
                    current['pages'].append(page_number)
                if n is not None:
                    warnings.append(f'{page_number}쪽: 번호 {n}가 중복되거나 역순입니다. 내부 목록·읽기 순서를 확인해 주세요.')
    if current:
        result.append(current)
    if not result and any(text.strip() for _, text in pages):
        result = [{'question_number': 1, 'text': '\n'.join(text for _, text in pages if text.strip()),
                   'pages': [p for p, text in pages if text.strip()]}]
        warnings.append('문항 번호를 찾지 못했습니다. 전체 텍스트를 임시 후보로 만들었습니다. 직접 분리해 주세요.')
    for i, item in enumerate(result):
        item['source_indexes'] = [i]
    return result, warnings + gap_warnings(result)

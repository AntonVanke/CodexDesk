import math

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QImage, QPainter, QFont, QFontMetrics


WIDTH, HEIGHT = 248, 160


def pack_bitmap(data):
    result = bytearray()
    pos = 0
    while pos < len(data):
        start = pos
        if data[pos] == 0:
            while pos < len(data) and data[pos] == 0 and pos-start < 128:
                pos += 1
            result.append(0x80 | (pos-start-1))
        else:
            while pos < len(data) and data[pos] != 0 and pos-start < 128:
                pos += 1
            result.append(pos-start-1)
            result.extend(data[start:pos])
    return bytes(result)


class TaskCarousel:
    def __init__(self):
        self.kind = 0
        self.page = 0
        self.question_index = 0
        self.question_id = None
        self.deadline = 0
        self.selected = None

    def frame(self, snapshot, now):
        tasks = snapshot['tasks']
        questions = [(task, question) for task in tasks for question in task['questions']]
        pages = max(1, math.ceil(len(tasks)/3))
        if self.kind and self.question_id not in [q['id'] for _, q in questions]:
            self.kind = 0
            self.deadline = 0
        if now >= self.deadline:
            if self.deadline and self.kind == 0 and questions:
                self.kind = 1
                self.question_index %= len(questions)
                self.question_id = questions[self.question_index][1]['id']
                self.question_index += 1
            else:
                if self.deadline:
                    self.page = (self.page + 1) % pages
                self.kind = 0
            self.deadline = now + (8 if self.kind else 3 if questions else 5)
        self.page %= pages
        question = next(((task, q) for task, q in questions if q['id'] == self.question_id), None) if self.kind else None
        visible = tasks[self.page*3:self.page*3+3]
        self.selected = question[0] if question else visible[int(now/5)%len(visible)] if visible else None
        return render_panel(snapshot, self.page, pages, question, questions, self.selected)


def render_panel(snapshot, page, pages, question, questions, selected=None):
    image = QImage(WIDTH, HEIGHT, QImage.Format.Format_Mono)
    image.setColor(0, 0xff000000)
    image.setColor(1, 0xffffffff)
    image.fill(0)
    painter = QPainter(image)
    painter.setPen(Qt.GlobalColor.white)

    def text(x, y, width, value, size=14, bold=False):
        font = QFont('Microsoft YaHei UI')
        font.setPixelSize(size)
        font.setBold(bold)
        font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        painter.setFont(font)
        value = QFontMetrics(font).elidedText(value, Qt.TextElideMode.ElideRight, width)
        painter.drawText(QRect(x, y, width, size+6), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, value)

    text(0, 0, 80, f'进行中 {snapshot["running"]}', 13)
    text(84, 0, 80, f'待回答 {snapshot["waiting"]}', 13)
    text(168, 0, 80, f'未读 {snapshot["unread"]}', 13)
    mask, choices = 0, 0
    if question:
        task, item = question
        index = next(i for i, (_, q) in enumerate(questions) if q['id'] == item['id'])
        text(0, 28, 196, task['title'], 13)
        if len(questions)>1:
            text(205, 28, 43, f'{index+1}/{len(questions)}', 13)
        font = QFont('Microsoft YaHei UI')
        font.setPixelSize(17)
        font.setBold(True)
        font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        remaining = ' '.join(item['text'].split())
        for line in range(3):
            end = 0
            while end < len(remaining) and metrics.horizontalAdvance(remaining[:end+1]) <= WIDTH:
                end += 1
            value = remaining[:end] if line < 2 else metrics.elidedText(remaining, Qt.TextElideMode.ElideRight, WIDTH)
            painter.drawText(0, 68 + line*21, value)
            remaining = remaining[end:]
            if not remaining:
                break
        choices = min(len(item['options']), 3)
        if choices <= 2:
            for i, option in enumerate(item['options'][:2]):
                text(i*126+7, 124, 105, option, 13)
        else:
            for i, option in enumerate(item['options'][:3]):
                text(7, 109+i*16, 232, option, 12)
        if not choices:
            text(0, 130, 248, '在电脑上确认计划' if item.get('kind')=='plan' else '在电脑上回答', 13)
    else:
        text(0, 28, 190, '任务总览', 13)
        if pages>1:
            text(205, 28, 43, f'{page+1}/{pages}', 13)
        for i, task in enumerate(snapshot['tasks'][page*3:page*3+3]):
            prefix = {'plan': '计划 · ', 'goal': '目标 · '}.get(task.get('mode'), '')
            if selected and task['id']==selected['id']:
                prefix = '› '+prefix
            text(0, 53+i*33, 155, prefix+task['title'], 16, True)
            text(164, 55+i*33, 84, task['activity'], 13)
            if task['questions']:
                mask |= 1 << i
            if task['unread']:
                mask |= 1 << (i+4)
        if not snapshot['tasks']:
            text(0, 83, WIDTH, '暂无任务动态', 17)
    painter.end()
    data = bytes(image.constBits())
    stride = image.bytesPerLine()
    bitmap = b''.join(data[y*stride:y*stride+31] for y in range(HEIGHT))
    return bitmap, int(question is not None), mask, choices


def render_model(task):
    image = QImage(136, 32, QImage.Format.Format_Mono)
    image.setColor(0, 0xff000000); image.setColor(1, 0xffffffff); image.fill(0)
    painter = QPainter(image); painter.setPen(Qt.GlobalColor.white)
    font = QFont('Microsoft YaHei UI'); font.setPixelSize(12)
    font.setStyleStrategy(QFont.StyleStrategy.NoAntialias); painter.setFont(font)
    if task:
        effort = {'minimal': '极低', 'low': '低', 'medium': '中', 'high': '高',
                  'xhigh': '极高', 'max': '最大', 'ultra': '超高'}.get(task.get('effort'), '—')
        speed = task.get('speed') or 0
        bolts = '⚡︎' * (2 if speed>=8 else 1 if speed>1 else 0)
        detail = effort + (' '+bolts if bolts else '')
        for y, value in [(0, task.get('model') or '—'), (16, detail)]:
            painter.drawText(QRect(0,y,136,16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                QFontMetrics(font).elidedText(value, Qt.TextElideMode.ElideRight, 136))
    painter.end()
    data=bytes(image.constBits()); stride=image.bytesPerLine()
    return b''.join(data[y*stride:y*stride+17] for y in range(32))

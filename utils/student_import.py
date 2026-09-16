"""
学生信息批量导入
================

用途：管理员上传 Excel(.xlsx) / CSV，批量为学生创建账号。

规则（按项目需求确认）
----------------------
* 默认**账号 = 密码 = 学号**
* 必填列：学号、姓名；可选列：邮箱、手机
* 学号沿用数据库的**全局唯一**约束（需求：只加学校标签，不改唯一性），
  因此：
    - 学号已存在且**同校**   -> 记为「已存在」跳过
    - 学号已存在但**属他校** -> 记为「冲突」跳过（不报错、不覆盖）
* 单行出错不影响其它行，最终返回完整报告供管理员核对

设计说明
--------
解析与落库分离：`parse_rows()` 纯解析（不碰数据库，便于测试），
`import_students()` 负责落库与分类统计。
"""
from __future__ import annotations

import csv
import io
from typing import Any, Dict, List, Optional, Tuple

# 表头别名：容忍常见的叫法差异
HEADER_ALIASES = {
    'student_id': {'学号', '学生学号', '账号', '学籍号', 'student_id', 'studentid', 'id'},
    'name': {'姓名', '名字', '学生姓名', 'name'},
    'email': {'邮箱', '电子邮箱', '邮件', 'email', 'e-mail'},
    'phone': {'手机', '手机号', '电话', '联系电话', 'phone', 'mobile', 'tel'},
}

REQUIRED_FIELDS = ('student_id', 'name')


class ImportError_(Exception):
    """导入过程中的可预期错误（用于返回友好提示）。"""


def _normalize_header(raw: str) -> Optional[str]:
    h = str(raw or '').strip().lower().replace(' ', '').replace('\u3000', '')
    for field, aliases in HEADER_ALIASES.items():
        if h in {a.lower() for a in aliases}:
            return field
    return None


def parse_rows(filename: str, content: bytes) -> Tuple[List[Dict[str, Any]], List[str]]:
    """解析上传文件为行字典列表。

    Returns:
        (rows, errors)
        rows: [{'row_no': 行号, 'student_id':..., 'name':..., 'email':..., 'phone':...}]
        errors: 文件级错误（表头缺失等）
    """
    name = (filename or '').lower()
    if name.endswith('.csv'):
        return _parse_csv(content)
    if name.endswith('.xlsx') or name.endswith('.xlsm'):
        return _parse_xlsx(content)
    raise ImportError_('仅支持 .xlsx / .csv 格式（.xls 请另存为 .xlsx）')


def _parse_csv(content: bytes) -> Tuple[List[Dict[str, Any]], List[str]]:
    text = None
    for enc in ('utf-8-sig', 'utf-8', 'gbk', 'gb18030'):
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ImportError_('CSV 编码无法识别，请用 UTF-8 或 GBK 保存')
    reader = csv.reader(io.StringIO(text))
    return _rows_from_matrix([r for r in reader])


def _parse_xlsx(content: bytes) -> Tuple[List[Dict[str, Any]], List[str]]:
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise ImportError_('服务器缺少 openpyxl，无法解析 xlsx；请改用 CSV')
    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as e:
        raise ImportError_('Excel 文件无法打开：%s' % str(e)[:80])
    ws = wb.active
    matrix = []
    for row in ws.iter_rows(values_only=True):
        matrix.append(['' if c is None else c for c in row])
    wb.close()
    return _rows_from_matrix(matrix)


def _rows_from_matrix(matrix: List[List[Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """把二维表转成行字典，自动定位表头行（允许前面有空行/标题行）。"""
    header_idx = None
    col_map: Dict[int, str] = {}
    for i, row in enumerate(matrix[:10]):        # 前 10 行内找表头
        m = {}
        for j, cell in enumerate(row):
            f = _normalize_header(cell)
            if f and f not in m.values():
                m[j] = f
        if all(f in m.values() for f in REQUIRED_FIELDS):
            header_idx, col_map = i, m
            break
    if header_idx is None:
        raise ImportError_('未找到表头，请确保表格包含「学号」「姓名」两列')

    rows, errors = [], []
    for i in range(header_idx + 1, len(matrix)):
        raw = matrix[i]
        if not any(str(c).strip() for c in raw):
            continue                              # 跳过空行
        item: Dict[str, Any] = {'row_no': i + 1}
        for j, field in col_map.items():
            v = raw[j] if j < len(raw) else ''
            if isinstance(v, float) and v.is_integer():
                v = int(v)                        # Excel 里学号被读成 123.0
            item[field] = str(v).strip()
        rows.append(item)
    if not rows:
        errors.append('表格里没有数据行')
    return rows, errors


def import_students(rows: List[Dict[str, Any]], school_id: int,
                    default_password_from_student_id: bool = True,
                    ) -> Dict[str, Any]:
    """把解析结果落库，返回分类报告。

    Returns:
        {
          'created': [{row_no, student_id, name}],
          'skipped': [{row_no, student_id, reason}],   # 同校已存在
          'conflict': [{row_no, student_id, reason}],  # 学号属他校
          'failed':  [{row_no, student_id, reason}],   # 缺字段/写库异常
          'total': n,
        }
    """
    from werkzeug.security import generate_password_hash
    from models import db
    from models.school import School
    from models.user import User

    school = db.session.get(School, school_id)
    if not school:
        raise ImportError_('学校不存在')

    report = {'created': [], 'skipped': [], 'conflict': [], 'failed': [],
              'total': len(rows), 'school': {'id': school.id, 'name': school.name}}

    # 预取已存在的学号 -> 所属学校，避免逐行查询
    existing = {u.student_id: u.school_id
                for u in User.query.filter(
                    User.student_id.in_([r.get('student_id', '') for r in rows if r.get('student_id')])
                ).all()} if rows else {}

    seen_in_file = set()
    for r in rows:
        sid = (r.get('student_id') or '').strip()
        name = (r.get('name') or '').strip()
        row_no = r.get('row_no')

        if not sid:
            report['failed'].append({'row_no': row_no, 'student_id': '',
                                     'reason': '缺少学号'})
            continue
        if not name:
            report['failed'].append({'row_no': row_no, 'student_id': sid,
                                     'reason': '缺少姓名'})
            continue
        if sid in seen_in_file:
            report['skipped'].append({'row_no': row_no, 'student_id': sid,
                                      'reason': '表格内重复（仅导入首次出现）'})
            continue

        if sid in existing:
            owner = existing[sid]
            if owner == school_id:
                report['skipped'].append({'row_no': row_no, 'student_id': sid,
                                          'reason': '该学号已在本校注册'})
            else:
                report['conflict'].append({
                    'row_no': row_no, 'student_id': sid,
                    'reason': '学号已被其它学校占用（学号全局唯一，未覆盖）'})
            continue

        try:
            pwd = sid if default_password_from_student_id else '123456'
            u = User(
                student_id=sid,
                school_id=school_id,
                name=name,
                role='student',
                is_approved=True,
                password_hash=generate_password_hash(pwd),
                email=(r.get('email') or '').strip() or None,
                phone=(r.get('phone') or '').strip() or None,
            )
            db.session.add(u)
            db.session.flush()
            seen_in_file.add(sid)
            existing[sid] = school_id
            report['created'].append({'row_no': row_no, 'student_id': sid, 'name': name})
        except Exception as e:                     # noqa: BLE001
            db.session.rollback()
            report['failed'].append({'row_no': row_no, 'student_id': sid,
                                     'reason': '写入失败：%s' % str(e)[:60]})

    db.session.commit()
    report['summary'] = {
        'created': len(report['created']),
        'skipped': len(report['skipped']),
        'conflict': len(report['conflict']),
        'failed': len(report['failed']),
    }
    return report


def build_template_xlsx() -> bytes:
    """生成导入模板（含表头与示例行）。"""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = '学生名单'
    ws.append(['学号', '姓名', '邮箱', '手机'])
    ws.append(['2024001', '张三', 'zhangsan@example.com', '13800000000'])
    ws.append(['2024002', '李四', '', ''])
    for i, w in enumerate((16, 12, 28, 16), start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

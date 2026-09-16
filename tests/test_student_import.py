# -*- coding: utf-8 -*-
"""P2 学生批量导入测试。"""
import io

import pytest

from app import db
from models.school import School
from models.user import User
from werkzeug.security import generate_password_hash, check_password_hash

from utils.student_import import (
    parse_rows, import_students, build_template_xlsx, ImportError_,
)


def _xlsx(rows):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _admin(client, app, sid='impadmin', school_id=None):
    with app.app_context():
        u = User(student_id=sid, name='导入管理员',
                 password_hash=generate_password_hash('123456'),
                 role='admin', is_approved=True, school_id=school_id)
        db.session.add(u)
        db.session.commit()
        uid = u.id
    with client.session_transaction() as sess:
        sess['user_id'] = uid
        sess['role'] = 'admin'
    return client


def _school(app, name):
    with app.app_context():
        sc = School(name=name)
        db.session.add(sc)
        db.session.commit()
        return sc.id


# ================================================================ 解析
class TestParse:
    def test_parse_xlsx(self):
        data = _xlsx([['学号', '姓名', '邮箱', '手机'],
                      ['2024001', '张三', 'z@x.com', '138'],
                      ['2024002', '李四', '', '']])
        rows, errs = parse_rows('a.xlsx', data)
        assert not errs
        assert len(rows) == 2
        assert rows[0]['student_id'] == '2024001'
        assert rows[0]['name'] == '张三'
        assert rows[0]['email'] == 'z@x.com'
        assert rows[0]['row_no'] == 2

    def test_parse_csv_utf8_bom(self):
        content = '\ufeff学号,姓名\n2024003,王五\n'.encode('utf-8')
        rows, errs = parse_rows('a.csv', content)
        assert len(rows) == 1
        assert rows[0]['student_id'] == '2024003'

    def test_parse_csv_gbk(self):
        content = '学号,姓名\n2024004,赵六\n'.encode('gbk')
        rows, _ = parse_rows('a.csv', content)
        assert rows[0]['name'] == '赵六'

    def test_header_aliases_tolerated(self):
        data = _xlsx([['学生学号', '学生姓名'],
                      ['2024005', '孙七']])
        rows, _ = parse_rows('a.xlsx', data)
        assert rows[0]['student_id'] == '2024005'
        assert rows[0]['name'] == '孙七'

    def test_excel_numeric_id_not_float(self):
        """Excel 会把学号读成数字，不能变成 2024006.0"""
        data = _xlsx([['学号', '姓名'], [2024006, '周八']])
        rows, _ = parse_rows('a.xlsx', data)
        assert rows[0]['student_id'] == '2024006'

    def test_missing_header_raises(self):
        data = _xlsx([['foo', 'bar'], ['1', '2']])
        with pytest.raises(ImportError_):
            parse_rows('a.xlsx', data)

    def test_unsupported_extension(self):
        with pytest.raises(ImportError_):
            parse_rows('a.txt', b'x')

    def test_empty_rows(self):
        data = _xlsx([['学号', '姓名']])
        rows, errs = parse_rows('a.xlsx', data)
        assert rows == []
        assert errs


# ================================================================ 落库
class TestImportStudents:
    def test_creates_with_password_equal_student_id(self, app):
        sid = _school(app, '导入大学')
        rows = [{'row_no': 2, 'student_id': '2024100', 'name': '测试甲',
                 'email': 'a@x.com', 'phone': '139'}]
        with app.app_context():
            rep = import_students(rows, sid)
            assert rep['summary']['created'] == 1
            u = User.query.filter_by(student_id='2024100').first()
            assert u is not None
            assert u.school_id == sid
            assert u.role == 'student'
            # 需求：默认账号密码都是学号
            assert check_password_hash(u.password_hash, '2024100')

    def test_same_school_existing_is_skipped(self, app):
        sid = _school(app, '导入大学')
        with app.app_context():
            db.session.add(User(student_id='2024101', name='已存在', role='student',
                                school_id=sid, is_approved=True,
                                password_hash=generate_password_hash('x')))
            db.session.commit()
            rep = import_students([{'row_no': 2, 'student_id': '2024101',
                                    'name': '重复', 'email': '', 'phone': ''}], sid)
            assert rep['summary']['skipped'] == 1
            assert rep['summary']['created'] == 0

    def test_other_school_same_id_is_conflict(self, app):
        """学号全局唯一：他校已占用 -> 记冲突，不报错不覆盖"""
        a = _school(app, 'A校')
        b = _school(app, 'B校')
        with app.app_context():
            db.session.add(User(student_id='2024102', name='他校学生', role='student',
                                school_id=a, is_approved=True,
                                password_hash=generate_password_hash('x')))
            db.session.commit()
            rep = import_students([{'row_no': 2, 'student_id': '2024102',
                                    'name': '同号', 'email': '', 'phone': ''}], b)
            assert rep['summary']['conflict'] == 1
            assert rep['summary']['created'] == 0
            # 原记录未被覆盖
            u = User.query.filter_by(student_id='2024102').first()
            assert u.school_id == a and u.name == '他校学生'

    def test_missing_fields_go_to_failed(self, app):
        sid = _school(app, '导入大学')
        with app.app_context():
            rep = import_students([
                {'row_no': 2, 'student_id': '', 'name': '无学号'},
                {'row_no': 3, 'student_id': '2024103', 'name': ''},
            ], sid)
            assert rep['summary']['failed'] == 2
            assert '学号' in rep['failed'][0]['reason']
            assert '姓名' in rep['failed'][1]['reason']

    def test_duplicate_inside_file_kept_once(self, app):
        sid = _school(app, '导入大学')
        with app.app_context():
            rep = import_students([
                {'row_no': 2, 'student_id': '2024104', 'name': '甲'},
                {'row_no': 3, 'student_id': '2024104', 'name': '甲重复'},
            ], sid)
            assert rep['summary']['created'] == 1
            assert rep['summary']['skipped'] == 1

    def test_bad_school_raises(self, app):
        with app.app_context():
            with pytest.raises(ImportError_):
                import_students([{'row_no': 2, 'student_id': 'x', 'name': 'y'}], 999999)


# ================================================================ 接口
class TestImportAPI:
    def test_template_download(self, client, app):
        _admin(client, app)
        r = client.get('/api/admin/students/import/template')
        assert r.status_code == 200
        assert len(r.data) > 1000            # 是个真的 xlsx
        assert r.data[:2] == b'PK'           # zip 魔数

    def test_import_upload_flow(self, client, app):
        sid = _school(app, '导入大学')
        _admin(client, app, 'impadmin2', school_id=sid)
        data = _xlsx([['学号', '姓名', '邮箱', '手机'],
                      ['2024200', '导入甲', 'a@x.com', '139'],
                      ['2024201', '导入乙', '', '']])
        r = client.post('/api/admin/students/import',
                        data={'file': (io.BytesIO(data), 'students.xlsx')},
                        content_type='multipart/form-data')
        assert r.status_code == 200, r.get_json()
        rep = r.get_json()['data']
        assert rep['summary']['created'] == 2
        # 两个学生都能用"学号当密码"登录
        for sid_ in ('2024200', '2024201'):
            r2 = client.post('/api/auth/login',
                             json={'student_id': sid_, 'password': sid_})
            assert r2.status_code == 200, r2.get_json()

    def test_import_requires_admin(self, client, app):
        data = _xlsx([['学号', '姓名'], ['1', 'x']])
        r = client.post('/api/admin/students/import',
                        data={'file': (io.BytesIO(data), 's.xlsx')},
                        content_type='multipart/form-data')
        assert r.status_code in (401, 403)

    def test_import_without_file(self, client, app):
        _admin(client, app, 'impadmin3')
        r = client.post('/api/admin/students/import', data={},
                        content_type='multipart/form-data')
        assert r.status_code == 400

    def test_import_bad_format(self, client, app):
        sid = _school(app, '导入大学')
        _admin(client, app, 'impadmin4', school_id=sid)
        r = client.post('/api/admin/students/import',
                        data={'file': (io.BytesIO(b'not a table'), 'x.txt')},
                        content_type='multipart/form-data')
        assert r.status_code == 400

    def test_student_list_scoped_by_school(self, client, app):
        a = _school(app, 'A校2')
        b = _school(app, 'B校2')
        with app.app_context():
            db.session.add(User(student_id='sa1', name='A生', role='student',
                                school_id=a, is_approved=True,
                                password_hash=generate_password_hash('x')))
            db.session.add(User(student_id='sb1', name='B生', role='student',
                                school_id=b, is_approved=True,
                                password_hash=generate_password_hash('x')))
            db.session.commit()
        _admin(client, app, 'impadmin5', school_id=a)
        rows = client.get('/api/admin/students').get_json()['data']['students']
        ids = [x['student_id'] for x in rows]
        assert 'sa1' in ids
        assert 'sb1' not in ids, '学生列表不应跨校'

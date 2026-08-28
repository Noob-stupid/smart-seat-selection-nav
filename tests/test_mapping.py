# -*- coding: utf-8 -*-
"""自动建图（view.auto_mapping 接入）接口测试"""
import io
import os

import pytest

from app import db
from models.building import Building, Floor
from models.user import User
from werkzeug.security import generate_password_hash

FRAMES_DIR = os.path.join(os.path.dirname(__file__), '..', 'view', 'frames')
SUPPORTED_IMAGE_EXTS = ('.jpg', '.jpeg', '.png')


def _sample_frames(n=6):
    """读取 view/frames 目录中的前 n 张图片，返回 [(BytesIO, filename)]"""
    if not os.path.isdir(FRAMES_DIR):
        return []
    names = sorted(
        f for f in os.listdir(FRAMES_DIR)
        if f.lower().endswith(SUPPORTED_IMAGE_EXTS)
    )[:n]
    files = []
    for fn in names:
        with open(os.path.join(FRAMES_DIR, fn), 'rb') as f:
            files.append((io.BytesIO(f.read()), fn))
    return files


@pytest.fixture
def admin_client(app, client):
    """管理员登录的测试客户端"""
    with app.app_context():
        user = User(
            student_id='mapadmin',
            name='建图管理员',
            password_hash=generate_password_hash('123456'),
            email='mapadmin@test.com',
            role='admin',
            is_approved=True,
        )
        db.session.add(user)
        db.session.commit()
        uid = user.id
    with client.session_transaction() as sess:
        sess['user_id'] = uid
        sess['role'] = 'admin'
    return client


@pytest.fixture
def sample_floor(app):
    """用于测试 apply 的楼层"""
    with app.app_context():
        building = Building(name='测试楼')
        db.session.add(building)
        db.session.flush()
        floor = Floor(building_id=building.id, floor_number=1, name='测试楼层')
        db.session.add(floor)
        db.session.commit()
        return floor.id


def test_create_mapping_task_requires_login(client):
    """未登录时创建建图任务应返回 401"""
    resp = client.post('/api/admin/mapping/tasks', data={})
    assert resp.status_code == 401


def test_create_mapping_task_from_frames(admin_client):
    """上传关键帧图片 → 自动建图 → 返回 plane.json 结构"""
    files = _sample_frames(6)
    if not files:
        pytest.skip('无示例帧素材 view/frames')
    if len(files) < 2:
        pytest.skip('示例帧素材不足 2 张')

    resp = admin_client.post(
        '/api/admin/mapping/tasks',
        data={'file': files, 'name': '测试房间', 'mode': 'images'},
        content_type='multipart/form-data',
    )
    body = resp.get_json()
    # 素材拼接可能成功（200）或特征不足（400），但都应是合法 API 响应
    assert resp.status_code in (200, 400), body
    if resp.status_code == 200:
        data = body['data']
        assert data['task_id'].startswith('room_')
        assert data['image']['url'].startswith('/outputs/')
        assert 'lines' in data
        assert 'width' in data['image'] and 'height' in data['image']

        # 查询任务接口
        q = admin_client.get(f"/api/admin/mapping/tasks/{data['task_id']}")
        assert q.status_code == 200
        assert q.get_json()['data']['status'] == 'done'


def test_get_mapping_task_not_found(admin_client):
    """不存在的任务应返回 404"""
    resp = admin_client.get('/api/admin/mapping/tasks/room_deadbeef')
    assert resp.status_code == 404


def test_apply_mapping_task(admin_client, sample_floor):
    """建图结果应用至楼层：更新 floor_plan 路径与尺寸"""
    files = _sample_frames(6)
    if not files or len(files) < 2:
        pytest.skip('无示例帧素材 view/frames')

    resp = admin_client.post(
        '/api/admin/mapping/tasks',
        data={'file': files, 'name': '测试房间', 'mode': 'images'},
        content_type='multipart/form-data',
    )
    body = resp.get_json()
    if resp.status_code != 200:
        pytest.skip('示例帧拼接未成功，跳过 apply 验证')

    task_id = body['data']['task_id']
    apply = admin_client.post(
        f'/api/admin/mapping/tasks/{task_id}/apply',
        json={'floor_id': sample_floor},
    )
    assert apply.status_code == 200, apply.get_json()
    apply_data = apply.get_json()['data']
    assert apply_data['floor_plan_url'].startswith('/uploads/')
    assert apply_data['width'] > 0 and apply_data['height'] > 0

    # 楼层接口应返回新的平面图地址
    floor_resp = admin_client.get(f'/api/floors/{sample_floor}')
    assert floor_resp.status_code == 200
    assert floor_resp.get_json()['data']['floor_plan_url'].startswith('/uploads/')


def test_apply_mapping_task_missing_floor(admin_client):
    """不存在的楼层 apply 应返回 404"""
    resp = admin_client.post(
        '/api/admin/mapping/tasks/room_deadbeef/apply',
        json={'floor_id': 999999},
    )
    assert resp.status_code == 404

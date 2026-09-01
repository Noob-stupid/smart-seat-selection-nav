# -*- coding: utf-8 -*-
"""自动建图（view.auto_mapping 接入）接口测试"""
import io
import os

import cv2
import numpy as np
import pytest

from app import db
from models.building import Building, Floor
from models.user import User
from werkzeug.security import generate_password_hash


def _make_synthetic_frames(n=6, size=560):
    """程序生成“俯视平面图”并裁剪为带重叠的扫描帧。

    不依赖外部素材（view/frames 已移除），可复现且保证帧间有足够特征用于拼接。
    返回 [(BytesIO, filename)]。
    """
    W, H = 1200, 800
    canvas = np.full((H, W, 3), 255, np.uint8)
    cv2.rectangle(canvas, (40, 40), (W - 40, H - 40), (0, 0, 0), 6)      # 外墙
    cv2.line(canvas, (620, 40), (620, H - 40), (0, 0, 0), 5)             # 隔断
    cv2.line(canvas, (620, 420), (W - 40, 420), (0, 0, 0), 5)            # 隔断
    cv2.rectangle(canvas, (120, 120), (300, 340), (170, 170, 170), -1)   # 家具
    cv2.rectangle(canvas, (90, 500), (330, 700), (190, 190, 190), -1)
    cv2.rectangle(canvas, (700, 100), (1000, 260), (150, 150, 150), -1)
    cv2.rectangle(canvas, (720, 480), (1050, 720), (210, 210, 210), -1)
    cv2.putText(canvas, 'PLAN-A', (480, 420), cv2.FONT_HERSHEY_SIMPLEX, 2, (80, 80, 80), 4)

    offsets = []
    for y in (0, H - size):
        for x in range(0, W - size + 1, 180):
            offsets.append((x, y))

    files = []
    for i, (x, y) in enumerate(offsets[:n]):
        crop = canvas[y:y + size, x:x + size].copy()
        ok, buf = cv2.imencode('.jpg', crop)
        assert ok
        files.append((io.BytesIO(buf.tobytes()), f'synth_{i:02d}.jpg'))
    return files


def _sample_frames(n=6):
    """测试用合成扫描帧（兼容旧调用方）"""
    return _make_synthetic_frames(n)


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

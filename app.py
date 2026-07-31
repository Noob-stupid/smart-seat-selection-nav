"""
智能选座与导航一体化系统 - 后端主入口
基于物联网感知的公共空间智能选座与导航系统
"""
import os
import uuid
import json
import time
import logging
import threading
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, request, jsonify, render_template,
    session, redirect, url_for, send_from_directory
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# 结构化日志
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO if os.getenv('DEBUG') != 'True' else logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

from config import Config
from models import db, socketio
from models.user import User
from models.building import Building, Floor, Seat
from models.reservation import Reservation, LockRecord
from models.sensor_data import SensorData
from utils import (
    locking, validate_return, BehaviorTracker,
    ImagePreprocessor, RecommendationEngine,
    RoadNetwork, PathFinder, NavigationService,
    SensorSimulator, RoadNetworkGenerator
)

load_dotenv()

# ---------------------------------------------------------------------------
# App 初始化
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config.from_object(Config)

# 尝试连接 MySQL，失败则回退到 SQLite
_mysql_uri = Config.SQLALCHEMY_DATABASE_URI
_try_mysql = os.getenv('DATABASE_URL')  # 显式指定则强制使用
if not _try_mysql:
    try:
        import pymysql
        conn = pymysql.connect(
            host=Config.DB_HOST, port=Config.DB_PORT,
            user=Config.DB_USER, password=Config.DB_PASSWORD,
            charset='utf8mb4',
        )
        # 确保数据库存在
        conn.cursor().execute(f'CREATE DATABASE IF NOT EXISTS `{Config.DB_NAME}` CHARACTER SET utf8mb4')
        conn.close()
        _try_mysql = True
        logger.info(f'MySQL 连接成功 ({Config.DB_HOST}:{Config.DB_PORT}/{Config.DB_NAME})')
    except Exception as e:
        logger.warning(f'MySQL 不可用 ({e})，回退到 SQLite')
        _try_mysql = False

app.config['SQLALCHEMY_DATABASE_URI'] = (
    _mysql_uri if _try_mysql
    else Config.SQLALCHEMY_DATABASE_URI_FALLBACK
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)
cors_origins = os.getenv('CORS_ORIGINS', '*')
socketio.init_app(app, cors_allowed_origins=cors_origins if cors_origins != '*' else '*')

os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(os.path.join(app.root_path, 'data', 'networks'), exist_ok=True)
os.makedirs(os.path.join(app.root_path, 'data', 'qrcodes'), exist_ok=True)
os.makedirs(os.path.join(app.root_path, 'data', 'overlays'), exist_ok=True)

# ---------------------------------------------------------------------------
# 模板上下文：每次渲染自动注入当前用户头像
# ---------------------------------------------------------------------------
@app.context_processor

def inject_user():
    """模板上下文：每次渲染自动注入当前登录用户及其头像"""
    user_id = session.get('user_id')
    if not user_id:
        return {}
    user = User.query.get(user_id)
    if user:
        return {'current_user': user, 'user_avatar': user.avatar_url or ''}
    return {}

# ---------------------------------------------------------------------------
# 全局服务实例
# ---------------------------------------------------------------------------
recommendation_engine = RecommendationEngine(weights=Config.AI_WEIGHTS)
navigation_service = NavigationService()
sensor_simulator = SensorSimulator(seat_count=50, scan_interval=Config.SENSOR_SCAN_INTERVAL)
behavior_trackers = {}

seat_state = {
    'locked': 0,
    'now_time': 0.0,
    'msg': '空闲',
    'running': False,
}

# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def get_or_create_behavior_tracker(user_id: str) -> BehaviorTracker:
    """获取用户的全局行为追踪器（不存在则创建）"""
    if user_id not in behavior_trackers:
        behavior_trackers[user_id] = BehaviorTracker(user_id=user_id)
    return behavior_trackers[user_id]


def api_response(data=None, message='success', code=200):
    """统一 API 返回格式：{code, message, data}"""
    return jsonify({'code': code, 'message': message, 'data': data}), code


def login_required(f):
    """登录校验装饰器：未登录时 JSON 请求返回 401，页面请求跳转登录页"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            if request.is_json or request.path.startswith('/api/'):
                return api_response(None, '请先登录', 401)
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """管理员权限校验装饰器：仅 admin / super_admin 可访问"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            if request.is_json or request.path.startswith('/api/'):
                return api_response(None, '请先登录', 401)
            return redirect(url_for('login', next=request.path))
        if session.get('role') not in ('admin', 'super_admin'):
            if request.is_json or request.path.startswith('/api/'):
                return api_response(None, '权限不足', 403)
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# 前端页面路由
# ---------------------------------------------------------------------------


@app.route('/')
@login_required
def index():
    """首页：展示所有启用的建筑物"""
    buildings = Building.query.filter_by(is_active=True).all()
    return render_template('index.html', buildings=buildings)


@app.route('/register', methods=['POST', 'GET'])
def register():
    """注册页面"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        password1 = request.form.get('password1')
        email = request.form.get('email')
        if not all([username, password, email, password1]):
            return render_template('register.html', error="请填写所有信息！")
        if password != password1:
            return render_template('register.html', error="再次输入密码有误！")
        # 检查用户名或邮箱是否已存在
        existing = User.query.filter(
            (User.student_id == username) | (User.email == email)
        ).first()
        if existing:
            return render_template('register.html', error="用户名已存在或邮箱已注册！")
        password_hash = generate_password_hash(password)
        new_user = User(
            student_id=username,
            email=email,
            password_hash=password_hash,
            name=username
        )
        try:
            db.session.add(new_user)
            db.session.commit()
            return render_template('login.html', success="注册成功！请登录")
        except Exception as e:
            db.session.rollback()
            return render_template('register.html', error="数据库错误")
    return render_template('register.html')


@app.route('/login', methods=['POST', 'GET'])
def login():
    """登录页面"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(student_id=username).first()
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['role'] = user.role
            session['username'] = user.student_id
            session['name'] = user.name
            session['avatar_url'] = user.avatar_url or ''
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="用户名或密码错误！")
    return render_template('login.html')


@app.route('/logout')
def logout():
    """退出登录"""
    session.clear()
    return redirect(url_for('index'))


# ---------------------------------------------------------------------------
# API: 认证
# ---------------------------------------------------------------------------


@app.route('/api/auth/login', methods=['POST'])
def api_login():
    """用户登录"""
    data = request.get_json()
    student_id = data.get('student_id', '').strip()
    password = data.get('password', '')

    if not student_id or not password:
        return api_response(None, '请填写账号和密码', 400)

    user = User.query.filter_by(student_id=student_id).first()
    if not user:
        return api_response(None, '账号或密码错误', 401)

    if not check_password_hash(user.password_hash, password):
        return api_response(None, '账号或密码错误', 401)

    # 管理员需审批通过
    if user.role == 'admin' and not user.is_approved:
        return api_response(None, '你的管理员账号正在审核中，请等待通知', 403)

    session['user_id'] = user.id
    session['role'] = user.role
    session['name'] = user.name
    session['student_id'] = user.student_id
    session['avatar_url'] = user.avatar_url or ''

    return api_response({
        'user_id': user.id,
        'name': user.name,
        'role': user.role,
        'student_id': user.student_id,
    }, '登录成功')


@app.route('/api/auth/register', methods=['POST'])
def api_register():
    """用户注册（管理员需审核，普通用户直接通过）"""
    data = request.get_json()
    student_id = data.get('student_id', '').strip()
    name = data.get('name', '').strip()
    password = data.get('password', '')
    confirm = data.get('confirm_password', '')
    role = data.get('role', 'student')

    if not student_id or not name or not password:
        return api_response(None, '请填写完整信息', 400)
    if len(password) < 6:
        return api_response(None, '密码至少6位', 400)
    if password != confirm:
        return api_response(None, '两次输入的密码不一致', 400)

    exist = User.query.filter_by(student_id=student_id).first()
    if exist:
        return api_response(None, '该账号已注册', 409)

    # 角色白名单校验：防止恶意用户注册为管理员
    ALLOWED_ROLES = {'student', 'admin'}
    if role not in ALLOWED_ROLES:
        return api_response(None, '无效的角色类型', 400)

    user = User(
        student_id=student_id,
        name=name,
        role=role,
        password_hash=generate_password_hash(password),
        # 管理员需审核，普通用户直接通过
        is_approved=(role != 'admin'),
    )
    db.session.add(user)
    db.session.commit()

    msg = '注册成功，请登录' if role != 'admin' else '注册成功，管理员账号需等待审核后登录'
    return api_response({
        'user_id': user.id,
        'name': user.name,
        'role': user.role,
    }, msg, 201)


@app.route('/api/auth/me', methods=['GET'])
def api_auth_me():
    """获取当前登录用户信息"""
    if 'user_id' not in session:
        return api_response(None, '未登录', 401)
    user = User.query.get(session['user_id'])
    if not user:
        session.clear()
        return api_response(None, '用户不存在', 401)
    return api_response(user.to_dict())


# ---------------------------------------------------------------------------
# API: 管理员审核
# ---------------------------------------------------------------------------

@app.route('/api/admin/pending-users', methods=['GET'])
@admin_required
def get_pending_users():
    """获取待审核的管理员列表"""
    users = User.query.filter_by(role='admin', is_approved=False).all()
    return api_response([u.to_dict() for u in users])


@app.route('/api/admin/approve/<int:user_id>', methods=['POST'])
@admin_required
def approve_user(user_id):
    """审核通过管理员"""
    user = User.query.get_or_404(user_id)
    if user.role != 'admin':
        return api_response(None, '该用户不是管理员', 400)
    user.is_approved = True
    db.session.commit()
    return api_response(None, '审核已通过')


@app.route('/api/admin/reject/<int:user_id>', methods=['POST'])
@admin_required
def reject_user(user_id):
    """驳回管理员申请（降为普通用户）"""
    user = User.query.get_or_404(user_id)
    if user.role != 'admin':
        return api_response(None, '该用户不是管理员', 400)
    user.role = 'student'
    user.is_approved = True
    db.session.commit()
    return api_response(None, '已驳回（降为普通用户）')


# ---------------------------------------------------------------------------
# API: 个人中心
# ---------------------------------------------------------------------------

@app.route('/api/profile', methods=['PUT'])
def api_update_profile():
    """更新个人资料"""
    if 'user_id' not in session:
        return api_response(None, '未登录', 401)
    user = User.query.get(session['user_id'])
    data = request.get_json()
    # 更新基础信息
    if data.get('name'):
        user.name = data['name']
    if data.get('email') is not None:
        user.email = data['email']
    if data.get('phone') is not None:
        user.phone = data['phone']
    # 更新个性标签
    if data.get('tags') is not None:
        prefs = user.preferences or {}
        prefs['tags'] = data['tags']
        user.preferences = prefs
    db.session.commit()
    return api_response(user.to_dict(), '资料已更新')


@app.route('/api/profile/avatar', methods=['POST'])
def api_upload_avatar():
    """上传头像"""
    if 'user_id' not in session:
        return api_response(None, '未登录', 401)
    user = User.query.get(session['user_id'])
    if 'avatar' not in request.files:
        return api_response(None, '请选择头像文件', 400)
    file = request.files['avatar']
    if file.filename == '':
        return api_response(None, '请选择头像文件', 400)
    ext = os.path.splitext(secure_filename(file.filename))[1].lower()
    if ext not in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
        return api_response(None, '仅支持 JPG/PNG/GIF/WEBP', 400)
    filename = f'avatar_{user.id}_{uuid.uuid4().hex[:8]}{ext}'
    filepath = os.path.join(Config.UPLOAD_FOLDER, filename)
    file.save(filepath)
    user.avatar_url = f'/uploads/{filename}'
    db.session.commit()
    return api_response({'avatar_url': user.avatar_url}, '头像已更新')


@app.route('/api/profile/password', methods=['PUT'])
def api_change_password():
    """修改密码"""
    if 'user_id' not in session:
        return api_response(None, '未登录', 401)
    user = User.query.get(session['user_id'])
    data = request.get_json()
    old_pw = data.get('old_password', '')
    new_pw = data.get('new_password', '')
    if not old_pw or not new_pw:
        return api_response(None, '请填写新旧密码', 400)
    if len(new_pw) < 6:
        return api_response(None, '新密码至少6位', 400)
    if not check_password_hash(user.password_hash, old_pw):
        return api_response(None, '原密码错误', 400)
    user.password_hash = generate_password_hash(new_pw)
    db.session.commit()
    return api_response(None, '密码已修改')


@app.route('/uploading')
@admin_required
def uploading():
    """平面图上传页（管理员）"""
    return render_template('uploading.html')


@app.route('/seat-map')
def seat_map():
    """选座地图页：按建筑物/楼层查看座位实时状态"""
    building_id = request.args.get('building_id', type=int)
    floor_id = request.args.get('floor_id', type=int)
    buildings = Building.query.filter_by(is_active=True).all()
    return render_template('seat_map.html', buildings=buildings,
                           current_building_id=building_id, current_floor_id=floor_id)


@app.route('/reservation')
@login_required
def reservation_page():
    """预约页面（模式2：选座式）"""
    building_id = request.args.get('building_id', type=int)
    floor_id = request.args.get('floor_id', type=int)
    seat_id = request.args.get('seat_id', type=int)
    buildings = Building.query.filter_by(is_active=True).all()
    current_building = None
    floors = []
    current_floor = None
    seats = []
    target_seat = None
    if building_id:
        current_building = Building.query.get(building_id)
        if current_building:
            floors = Floor.query.filter_by(building_id=building_id, is_active=True).order_by(Floor.floor_number).all()
            if floor_id:
                current_floor = Floor.query.get(floor_id)
                if current_floor:
                    seats = Seat.query.filter_by(floor_id=floor_id, is_active=True, status='free').order_by(Seat.seat_label).all()
                    if seat_id:
                        target_seat = Seat.query.get(seat_id)
    # 当前用户的预约记录
    user_id = session.get('user_id')
    reservations = Reservation.query.filter_by(user_id=user_id).order_by(Reservation.created_at.desc()).limit(20).all() if user_id else []
    # 给预约附加座位标签
    for r in reservations:
        if r.seat:
            r.seat_label = r.seat.seat_label
        else:
            r.seat_label = '座位#' + str(r.seat_id)
    return render_template('reservation.html', buildings=buildings,
                           current_building=current_building, floors=floors,
                           current_floor=current_floor, seats=seats,
                           target_seat=target_seat, reservations=reservations)


@app.route('/reservation/do', methods=['POST'])
@login_required
def do_reserve():
    """表单方式提交预约：占用座位并生成预约记录"""
    seat_id = request.form.get('seat_id', type=int)
    duration = request.form.get('duration', 2, type=int)
    seat = Seat.query.get(seat_id)
    if not seat or seat.status != 'free':
        return redirect(url_for('reservation_page'))
    now = datetime.utcnow()
    reservation = Reservation(
        user_id=session['user_id'], seat_id=seat_id,
        building_id=seat.floor.building_id,
        start_time=now, end_time=now + timedelta(hours=duration),
        qr_token=uuid.uuid4().hex[:16], status='pending',
    )
    db.session.add(reservation)
    seat.status = 'occupied'
    seat.current_user_id = session['user_id']
    db.session.commit()
    return redirect(url_for('reservation_page'))


@app.route('/reservation/<int:reservation_id>/cancel', methods=['POST'])
@login_required
def cancel_reserve(reservation_id):
    """取消表单预约：释放座位"""
    reservation = Reservation.query.get_or_404(reservation_id)
    if reservation.user_id != session['user_id']:
        return redirect(url_for('reservation_page'))
    if reservation.status == 'pending':
        reservation.status = 'cancelled'
        seat = reservation.seat
        if seat:
            seat.status = 'free'
            seat.current_user_id = None
        db.session.commit()
    return redirect(url_for('reservation_page'))


@app.route('/navigation')
def navigation_page():
    """室内导航页面"""
    building_id = request.args.get('building_id', type=int)
    floor_id = request.args.get('floor_id', type=int)
    seat_id = request.args.get('seat_id', type=int)
    buildings = Building.query.filter_by(is_active=True).all()
    seat = Seat.query.get(seat_id) if seat_id else None
    return render_template('navigation.html', buildings=buildings,
                           current_building_id=building_id,
                           current_floor_id=floor_id, target_seat=seat)


@app.route('/profile')
@login_required
def profile_page():
    """个人中心页面"""
    user = User.query.get(session['user_id'])
    return render_template('profile.html', user=user)


@app.route('/admin')
@admin_required
def admin_dashboard():
    """管理后台首页"""
    return render_template('admin/dashboard.html')


@app.route('/admin/buildings')
@admin_required
def admin_buildings():
    """建筑物管理页"""
    return render_template('admin/buildings.html')


@app.route('/admin/floor-plan')
@admin_required
def admin_floor_plan():
    """楼层平面图与路网管理页"""
    building_id = request.args.get('building_id', type=int)
    floor_id = request.args.get('floor_id', type=int)
    buildings = Building.query.filter_by(is_active=True).all()
    return render_template('admin/floor_plan.html', buildings=buildings,
                           current_building_id=building_id, current_floor_id=floor_id)


@app.route('/admin/settings')
@admin_required
def admin_settings():
    """系统设置页（锁定参数/权重/传感器等）"""
    return render_template('admin/settings.html')


@app.route('/admin/behavior')
@admin_required
def admin_behavior():
    """行为感知分析页"""
    return render_template('admin/behavior.html')


@app.route('/admin/approvals')
@admin_required
def admin_approvals():
    """管理员账号审核页"""
    return render_template('admin/approvals.html')


# ---------------------------------------------------------------------------
# API: 建筑物与楼层管理
# ---------------------------------------------------------------------------


@app.route('/api/regions', methods=['GET'])
def get_regions():
    """获取所有区域/城市列表（按建筑数量排序）"""
    from sqlalchemy import text
    rows = db.session.execute(
        text('SELECT region, COUNT(*) as cnt FROM buildings WHERE is_active=1 AND region IS NOT NULL AND region!="" GROUP BY region ORDER BY cnt DESC')
    ).fetchall()
    regions = [{'name': r[0], 'count': r[1]} for r in rows]
    return api_response(regions)


@app.route('/api/search/venues', methods=['GET'])
def search_venues():
    """搜索场所（按名称/地址/区域模糊匹配）"""
    q = request.args.get('q', '').strip()
    if not q or len(q) < 1:
        return api_response([])

    results = Building.query.filter(
        Building.is_active == True,
        db.or_(
            Building.name.ilike(f'%{q}%'),
            Building.alias.ilike(f'%{q}%'),
            Building.region.ilike(f'%{q}%'),
            Building.address.ilike(f'%{q}%'),
        )
    ).order_by(Building.name).all()
    return api_response([b.to_dict() for b in results])


@app.route('/api/buildings', methods=['GET'])
def get_buildings():
    """获取建筑物列表（附带总座位数/空闲座位数统计）"""
    query = Building.query.filter_by(is_active=True)
    region = request.args.get('region')
    if region:
        query = query.filter_by(region=region)
    buildings = query.order_by(Building.name).all()
    result = []
    for b in buildings:
        d = b.to_dict()
        total = Seat.query.join(Floor).filter(Floor.building_id == b.id, Seat.is_active == True).count()
        free = Seat.query.join(Floor).filter(Floor.building_id == b.id, Seat.is_active == True, Seat.status == 'free').count()
        d['total_seats'] = total
        d['free_seats'] = free
        result.append(d)
    return api_response(result)


@app.route('/api/buildings', methods=['POST'])
@admin_required
def create_building():
    """创建建筑物"""
    data = request.get_json()
    building = Building(
        name=data['name'], alias=data.get('alias'),
        region=data.get('region'),
        address=data.get('address'), lat=data.get('lat'),
        lng=data.get('lng'), description=data.get('description'),
    )
    db.session.add(building)
    db.session.commit()
    return api_response(building.to_dict(), '建筑物创建成功', 201)


@app.route('/api/buildings/<int:building_id>', methods=['GET'])
def get_building(building_id):
    """获取建筑物详情（含楼层列表）"""
    building = Building.query.get_or_404(building_id)
    result = building.to_dict()
    floors = Floor.query.filter_by(building_id=building_id, is_active=True)\
        .order_by(Floor.floor_number).all()
    result['floors'] = [f.to_dict() for f in floors]
    return api_response(result)


@app.route('/api/buildings/<int:building_id>', methods=['PUT'])
@admin_required
def update_building(building_id):
    """更新建筑物信息"""
    building = Building.query.get_or_404(building_id)
    data = request.get_json()
    for field in ['name', 'alias', 'region', 'address', 'lat', 'lng', 'description']:
        if field in data:
            setattr(building, field, data[field])
    db.session.commit()
    return api_response(building.to_dict())


@app.route('/api/buildings/<int:building_id>', methods=['DELETE'])
@admin_required
def delete_building(building_id):
    """软删除建筑物（标记失效，不物理删除）"""
    building = Building.query.get_or_404(building_id)
    building.is_active = False
    db.session.commit()
    return api_response(None, '已删除')


@app.route('/api/buildings/<int:building_id>/floors', methods=['POST'])
@admin_required
def add_floor(building_id):
    """为建筑物添加楼层"""
    Building.query.get_or_404(building_id)
    data = request.get_json()
    floor = Floor(
        building_id=building_id,
        floor_number=data['floor_number'],
        name=data.get('name'),
    )
    db.session.add(floor)
    db.session.commit()
    return api_response(floor.to_dict(), '楼层添加成功', 201)


@app.route('/api/floors/<int:floor_id>', methods=['GET'])
def get_floor(floor_id):
    """获取楼层详情（含座位列表）"""
    floor = Floor.query.get_or_404(floor_id)
    result = floor.to_dict()
    seats = Seat.query.filter_by(floor_id=floor_id, is_active=True).all()
    result['seats'] = [s.to_dict() for s in seats]
    return api_response(result)


@app.route('/api/floors/<int:floor_id>', methods=['PUT'])
@admin_required
def update_floor(floor_id):
    """更新楼层信息（平面图路径等）"""
    floor = Floor.query.get_or_404(floor_id)
    data = request.get_json()
    has_new_plan = 'floor_plan_path' in data and data['floor_plan_path'] != floor.floor_plan_path
    for field in ['name', 'floor_number', 'floor_plan_path',
                  'floor_plan_width', 'floor_plan_height', 'road_network_path']:
        if field in data:
            setattr(floor, field, data[field])
    # 如果更新了平面图，清除旧路网（因为路网需要基于新平面图重新生成）
    if has_new_plan and floor.road_network_path:
        old_network = floor.road_network_path
        floor.road_network_path = None
        try:
            if os.path.exists(old_network):
                os.remove(old_network)
        except Exception:
            pass
    db.session.commit()
    return api_response(floor.to_dict())


@app.route('/api/floors/<int:floor_id>', methods=['DELETE'])
@admin_required
def delete_floor(floor_id):
    """删除楼层"""
    floor = Floor.query.get_or_404(floor_id)
    floor.is_active = False
    db.session.commit()
    return api_response(None, '已删除')


# ---------------------------------------------------------------------------
# API: 座位管理
# ---------------------------------------------------------------------------


@app.route('/api/floors/<int:floor_id>/seats', methods=['POST'])
@admin_required
def add_seats(floor_id):
    """批量添加座位（支持单个对象或对象数组）"""
    Floor.query.get_or_404(floor_id)
    data = request.get_json()
    seats_data = data if isinstance(data, list) else [data]
    created = []
    for s in seats_data:
        seat = Seat(
            floor_id=floor_id, seat_label=s['seat_label'],
            seat_type=s.get('seat_type', 'normal'),
            x=s['x'], y=s['y'],
            width=s.get('width', 30), height=s.get('height', 30),
            rotation=s.get('rotation', 0),
        )
        db.session.add(seat)
        created.append(seat)
    db.session.commit()
    return api_response([s.to_dict() for s in created],
                        f'成功添加{len(created)}个座位', 201)


@app.route('/api/seats/<int:seat_id>', methods=['PUT'])
@admin_required
def update_seat(seat_id):
    """更新座位信息（坐标/类型/红外等）"""
    seat = Seat.query.get_or_404(seat_id)
    data = request.get_json()
    for field in ['seat_label', 'seat_type', 'x', 'y', 'width', 'height',
                  'rotation', 'ir_front', 'ir_back', 'nearest_node_id']:
        if field in data:
            setattr(seat, field, data[field])
    db.session.commit()
    return api_response(seat.to_dict())


@app.route('/api/seats/<int:seat_id>', methods=['DELETE'])
@admin_required
def delete_seat(seat_id):
    """软删除座位（标记失效）"""
    seat = Seat.query.get_or_404(seat_id)
    seat.is_active = False
    db.session.commit()
    return api_response(None, '已删除')


# ---------------------------------------------------------------------------
# API: 座位状态与传感器
# ---------------------------------------------------------------------------


@app.route('/api/status')
def get_status():
    """获取座位状态统计（总数/空闲/占用/锁定/异常）"""
    total = Seat.query.filter_by(is_active=True).count()
    free = Seat.query.filter_by(is_active=True, status='free').count()
    occupied = Seat.query.filter_by(is_active=True, status='occupied').count()
    locked = Seat.query.filter_by(is_active=True, status='locked').count()
    error = Seat.query.filter_by(is_active=True, status='error').count()
    return api_response({
        'total': total, 'free': free, 'occupied': occupied,
        'locked': locked, 'error': error,
        'lock_running': seat_state.get('running', False),
        'lock_msg': seat_state.get('msg', ''),
        'updated_at': datetime.utcnow().isoformat(),
    })


@app.route('/api/seats', methods=['GET'])
def get_seats():
    """获取座位列表（可按楼层/状态过滤，占用座位附用户信息）"""
    query = Seat.query.filter_by(is_active=True)
    floor_id = request.args.get('floor_id', type=int)
    status = request.args.get('status')
    if floor_id:
        query = query.filter_by(floor_id=floor_id)
    if status:
        query = query.filter_by(status=status)
    seats = query.order_by(Seat.seat_label).all()
    result = []
    for s in seats:
        d = s.to_dict()
        if s.floor:
            d['floor_number'] = s.floor.floor_number
            d['floor_name'] = s.floor.name
            if s.floor.building:
                d['building_id'] = s.floor.building.id
                d['building_name'] = s.floor.building.name
        # 占用座位附加用户信息（用于桌面端显示头像）
        if s.status == 'occupied' and s.current_user_id:
            occupant = User.query.get(s.current_user_id)
            if occupant:
                d['occupant_name'] = occupant.name
                d['occupant_avatar'] = occupant.avatar_url or ''
        result.append(d)
    return api_response(result)


@app.route('/api/sensor/report', methods=['POST'])
def sensor_report():
    """红外交叉校验：两束同时遮挡 → 有人"""
    data = request.get_json()
    seat_id = data.get('seat_id')
    ir_front = data.get('ir_front', 0)
    ir_back = data.get('ir_back', 0)

    seat = Seat.query.get(seat_id)
    if not seat:
        return api_response(None, '座位不存在', 404)

    db.session.add(SensorData(seat_id=seat_id, ir_front=ir_front, ir_back=ir_back))
    seat.ir_front = ir_front
    seat.ir_back = ir_back
    seat.last_scan_time = datetime.utcnow()

    both = (ir_front == 1 and ir_back == 1)
    if both:
        if seat.status == 'free':
            seat.status = 'occupied'
            seat.occupied_since = datetime.utcnow()
            seat.lock_available_since = datetime.utcnow() + timedelta(minutes=Config.LOCK_M_DEFAULT)
        seat.consecutive_empty = 0
    else:
        seat.consecutive_empty += 1
        if seat.consecutive_empty >= 2 and seat.status == 'occupied':
            seat.status = 'free'
            seat.current_user_id = None
            seat.occupied_since = None
            seat.lock_available_since = None

    if seat.last_scan_time:
        hours_since = (datetime.utcnow() - seat.last_scan_time).total_seconds() / 3600
        if hours_since > 24 and seat.status != 'error':
            seat.status = 'error'
            seat.error_since = datetime.utcnow()

    db.session.commit()
    socketio.emit('seat_update', {
        'seat_id': seat_id, 'status': seat.status,
        'ir_front': ir_front, 'ir_back': ir_back,
    })
    return api_response({'seat_id': seat_id, 'status': seat.status,
                         'consecutive_empty': seat.consecutive_empty})


# ---------------------------------------------------------------------------
# API: 锁定机制（核心3★核心创新）
# ---------------------------------------------------------------------------


def run_locking(m, n):
    """后台线程执行锁定流程（调用 locking），并更新全局锁定状态"""
    global seat_state
    seat_state['running'] = True
    seat_state['msg'] = '锁定任务运行中...'
    try:
        result = locking(m, n)
        if isinstance(result, dict):
            seat_state.update(result)
        else:
            seat_state['msg'] = '锁定结束'
    except Exception as e:
        seat_state['msg'] = f'错误: {e}'
    finally:
        seat_state['running'] = False


@app.route('/api/lock/start', methods=['POST'])
def start_lock():
    """启动座位锁定（核心创新：连续占用满 m 分钟后可锁定，防抢座）"""
    data = request.get_json()
    seat_id = data.get('seat_id')
    user_id = data.get('user_id')
    m = float(data.get('m', Config.LOCK_M_DEFAULT))
    n = float(data.get('n', Config.LOCK_N_DEFAULT))

    seat = Seat.query.get(seat_id)
    if not seat:
        return api_response(None, '座位不存在', 404)
    if seat.status != 'occupied':
        return api_response(None, '座位未被占用，无法锁定', 400)
    if seat.occupied_since:
        elapsed = (datetime.utcnow() - seat.occupied_since).total_seconds() / 60
        if elapsed < m:
            return api_response(None,
                                f'需连续占用{m}分钟后方可锁定，当前已占用{elapsed:.1f}分钟', 400)

    seat.status = 'locked'
    seat.current_user_id = user_id
    db.session.commit()

    threading.Thread(target=run_locking, args=(m, n), daemon=True).start()

    record = LockRecord(
        user_id=user_id, seat_id=seat_id,
        floor_id=seat.floor_id, lock_start=datetime.utcnow(),
    )
    db.session.add(record)
    db.session.commit()

    socketio.emit('seat_update', {'seat_id': seat_id, 'status': 'locked'})
    return api_response({
        'seat_id': seat_id, 'status': 'locked',
        'm_minutes': m, 'n_minutes': n,
    }, '锁定成功')


@app.route('/api/lock/release', methods=['POST'])
def release_lock():
    """手动解除锁定（用户暂离后返回，结束锁定并记录时长）"""
    data = request.get_json()
    seat_id = data.get('seat_id')
    user_id = data.get('user_id')

    seat = Seat.query.get(seat_id)
    if not seat or seat.status != 'locked':
        return api_response(None, '座位未锁定', 400)

    record = LockRecord.query.filter_by(
        seat_id=seat_id, user_id=user_id, lock_end=None
    ).first()
    if record:
        record.lock_end = datetime.utcnow()
        record.duration_sec = (record.lock_end - record.lock_start).total_seconds()
        record.auto_unlocked = False

    seat.status = 'free' if not data.get('keep_occupied') else 'occupied'
    seat.current_user_id = None
    db.session.commit()

    socketio.emit('seat_update', {'seat_id': seat_id, 'status': seat.status})
    return api_response({'seat_id': seat_id, 'status': seat.status}, '已解锁')


@app.route('/api/lock/status', methods=['GET'])
def lock_status():
    """查询当前锁定任务运行状态"""
    return jsonify(seat_state)


@app.route('/api/lock/start-legacy', methods=['GET'])
def lockingo_legacy():
    """旧版锁定启动接口（GET 方式触发，兼容历史前端）"""
    m = float(request.args.get('m', Config.LOCK_M_DEFAULT))
    n = float(request.args.get('n', Config.LOCK_N_DEFAULT))
    threading.Thread(target=run_locking, args=(m, n), daemon=True).start()
    return jsonify({'msg': '锁定任务已启动', 'running': True})


# ---------------------------------------------------------------------------
# API: 最短有效回归时长机制
# ---------------------------------------------------------------------------


@app.route('/api/validate-return', methods=['POST'])
def api_validate_return():
    """验证用户回归是否有效（防止"每 n-1 分钟回来晃一下"规避检测）"""
    data = request.get_json()
    seat_id = data.get('seat_id')
    user_id = data.get('user_id')
    min_duration = float(data.get('min_duration', Config.LOCK_T_DEFAULT))

    seat = Seat.query.get(seat_id)
    if not seat:
        return api_response(None, '座位不存在', 404)

    tracker = get_or_create_behavior_tracker(str(user_id))
    is_valid = True
    if is_valid:
        tracker.record_detection(True, 0)
        tracker.record_return(True)
    else:
        tracker.record_detection(False, min_duration)

    return api_response({'valid': is_valid, 'min_duration': min_duration})


# ---------------------------------------------------------------------------
# API: 行为感知演进机制
# ---------------------------------------------------------------------------


@app.route('/api/behavior/report/<int:user_id>', methods=['GET'])
def get_behavior_report(user_id):
    """获取指定用户的行为感知分析报告"""
    tracker = get_or_create_behavior_tracker(str(user_id))
    return api_response(tracker.get_report())


@app.route('/api/admin/abnormal-users', methods=['GET'])
@admin_required
def get_abnormal_users():
    """获取行为异常（疑似恶意锁座）的用户列表"""
    abnormal = []
    for uid, tracker in behavior_trackers.items():
        if tracker.is_abnormal():
            report = tracker.get_report()
            user = User.query.get(int(uid))
            if user:
                report['user_name'] = user.name
                report['student_id'] = user.student_id
            abnormal.append(report)
    return api_response(abnormal)


# ---------------------------------------------------------------------------
# API: AI 推荐
# ---------------------------------------------------------------------------


@app.route('/api/recommend', methods=['GET'])
def get_recommendations():
    """AI 加权推荐空闲座位（距离/区域热度/偏好匹配/拥挤度）"""
    user_id = request.args.get('user_id', type=int)
    building_id = request.args.get('building_id', type=int)
    floor_id = request.args.get('floor_id', type=int)
    user_x = request.args.get('user_x', 0, type=float)
    user_y = request.args.get('user_y', 0, type=float)
    top_k = request.args.get('top_k', 10, type=int)

    if not building_id:
        return api_response(None, '请指定建筑物', 400)
    if not user_id:
        user_id = 1

    result = recommendation_engine.get_recommendations(
        user_id=user_id, building_id=building_id,
        floor_id=floor_id, user_x=user_x, user_y=user_y, top_k=top_k,
    )
    return api_response(result)


@app.route('/api/admin/weights', methods=['GET', 'PUT'])
@admin_required
def manage_weights():
    """查看 / 更新 AI 推荐权重（管理员）"""
    if request.method == 'GET':
        return api_response({
            'weights': recommendation_engine.weights,
            'weight_names': ['距离', '区域热度', '偏好匹配', '场所拥挤度'],
        })
    data = request.get_json()
    try:
        recommendation_engine.update_weights(data.get('weights'))
        return api_response({'weights': recommendation_engine.weights}, '权重更新成功')
    except ValueError as e:
        return api_response(None, str(e), 400)


# ---------------------------------------------------------------------------
# API: 预约系统（模式2：选座式）
# ---------------------------------------------------------------------------


@app.route('/api/reservations', methods=['POST'])
def create_reservation():
    """创建座位预约（模式2：选座式，占用座位并生成二维码凭证）"""
    data = request.get_json()
    user_id = data.get('user_id') or session.get('user_id')
    seat_id = data.get('seat_id')
    start_time = datetime.fromisoformat(data['start_time']) if data.get('start_time') else datetime.utcnow()
    end_time = datetime.fromisoformat(data['end_time']) if data.get('end_time') else start_time + timedelta(hours=2)

    seat = Seat.query.get(seat_id)
    if not seat or seat.status != 'free':
        return api_response(None, '座位不可预约', 400)

    qr_token = uuid.uuid4().hex[:16]
    reservation = Reservation(
        user_id=user_id, seat_id=seat_id,
        building_id=seat.floor.building_id,
        start_time=start_time, end_time=end_time,
        qr_token=qr_token, status='pending',
    )
    db.session.add(reservation)
    seat.status = 'occupied'
    seat.current_user_id = user_id
    db.session.commit()
    return api_response(reservation.to_dict(), '预约成功', 201)


@app.route('/api/reservations', methods=['GET'])
def get_reservations():
    """获取预约列表（可按用户/状态过滤）"""
    user_id = request.args.get('user_id', type=int)
    status = request.args.get('status')
    query = Reservation.query
    if user_id:
        query = query.filter_by(user_id=user_id)
    if status:
        query = query.filter_by(status=status)
    reservations = query.order_by(Reservation.created_at.desc()).all()
    return api_response([r.to_dict() for r in reservations])


@app.route('/api/reservations/<int:reservation_id>/checkin', methods=['POST'])
def checkin_reservation(reservation_id):
    """预约签到：pending → checked_in"""
    reservation = Reservation.query.get_or_404(reservation_id)
    if reservation.status != 'pending':
        return api_response(None, '预约状态无效', 400)
    reservation.status = 'checked_in'
    reservation.checkin_time = datetime.utcnow()
    db.session.commit()
    socketio.emit('seat_update', {'seat_id': reservation.seat_id, 'status': 'occupied'})
    return api_response(reservation.to_dict(), '签到成功')


@app.route('/api/reservations/<int:reservation_id>/cancel', methods=['POST'])
def cancel_reservation(reservation_id):
    """取消预约并释放座位"""
    reservation = Reservation.query.get_or_404(reservation_id)
    if reservation.status in ['completed', 'cancelled']:
        return api_response(None, '预约已结束', 400)
    reservation.status = 'cancelled'
    seat = Seat.query.get(reservation.seat_id)
    if seat:
        seat.status = 'free'
        seat.current_user_id = None
    db.session.commit()
    socketio.emit('seat_update', {'seat_id': reservation.seat_id, 'status': 'free'})
    return api_response(None, '已取消')


# ---------------------------------------------------------------------------
# API: 导航
# ---------------------------------------------------------------------------


@app.route('/api/navigation/plan', methods=['POST'])
def plan_navigation():
    """室内路径规划（支持单层寻路与跨层导航）"""
    data = request.get_json()
    from_floor_id = data.get('from_floor_id')
    to_floor_id = data.get('to_floor_id', from_floor_id)
    from_node = data.get('from_node')
    to_node = data.get('to_node')

    # 自动加载路网（如果尚未加载）
    for fid in set(filter(None, [from_floor_id, to_floor_id])):
        if not navigation_service.get_path_finder(fid):
            floor = Floor.query.get(fid)
            if floor and floor.road_network_path and os.path.exists(floor.road_network_path):
                nav_loaded = navigation_service.load_network(fid, floor.road_network_path)
                if nav_loaded:
                    logger.info('导航路网已自动加载: floor=%s, nodes=%d, edges=%d',
                                fid, len(nav_loaded.nodes), len(nav_loaded.edges))

    finder_from = navigation_service.get_path_finder(from_floor_id) if from_floor_id else None
    finder_to = navigation_service.get_path_finder(to_floor_id) if to_floor_id else None

    if not from_node and data.get('from_x') is not None and finder_from:
        from_node = finder_from.find_nearest_node(data['from_x'], data['from_y'])
    if not to_node and data.get('to_x') is not None and finder_to:
        to_node = finder_to.find_nearest_node(data['to_x'], data['to_y'])

    if not from_node or not to_node:
        detail = []
        if not finder_from: detail.append(f'起点楼层({from_floor_id})路网未加载')
        if not from_node and finder_from: detail.append(f'起点({data.get("from_x")},{data.get("from_y")})附近无路网节点')
        if not finder_to: detail.append(f'终点楼层({to_floor_id})路网未加载')
        if not to_node and finder_to: detail.append(f'终点({data.get("to_x")},{data.get("to_y")})附近无路网节点')
        return api_response(None, '路径规划失败：' + '；'.join(detail) if detail else '无法确定起点或终点', 400)

    if from_floor_id != to_floor_id:
        lou_ti_kou_jie_dian = _qu_lou_ti_kou_jie_dian(from_floor_id, to_floor_id)
        result = navigation_service.plan_cross_floor(
            from_floor_id, to_floor_id, from_node, to_node, lou_ti_kou_jie_dian)
    else:
        result = navigation_service.plan_intra_floor(from_floor_id, from_node, to_node)

    return api_response(result)


@app.route('/api/navigation/locate', methods=['POST'])
def locate_user():
    """用户定位：扫码定位(qr) 或 手动选点吸附(click)"""
    data = request.get_json()
    loc_type = data.get('type', 'click')
    floor_id = data.get('floor_id')
    # 自动加载路网
    if floor_id and not navigation_service.get_path_finder(floor_id):
        floor = Floor.query.get(floor_id)
        if floor and floor.road_network_path and os.path.exists(floor.road_network_path):
            navigation_service.load_network(floor_id, floor.road_network_path)
    if loc_type == 'qr':
        result = navigation_service.locate_user_by_qr(floor_id, data['node_id'])
    else:
        result = navigation_service.locate_user_by_click(
            floor_id, data.get('click_x', 0), data.get('click_y', 0))
    return api_response(result)


# ---------------------------------------------------------------------------
# API: 路网管理（管理员）
# ---------------------------------------------------------------------------


@app.route('/api/admin/network/generate', methods=['POST'])
@admin_required
def generate_network():
    """根据平面图自动生成路网（无图时按座位坐标生成简易路网）"""
    data = request.get_json()
    floor_id = data['floor_id']
    image_path = data.get('image_path')

    floor = Floor.query.get_or_404(floor_id)
    if not image_path and floor.floor_plan_path:
        image_path = floor.floor_plan_path

    seats_data = data.get('seats')
    if not seats_data:
        seats = Seat.query.filter_by(floor_id=floor_id, is_active=True).all()
        seats_data = [{'x': s.x, 'y': s.y, 'label': s.seat_label} for s in seats]

    if not seats_data:
        return api_response(None, '当前楼层没有座位，请先添加座位', 400)

    generator = RoadNetworkGenerator()
    try:
        if image_path and os.path.exists(image_path):
            # 有平面图：基于图像提取路网
            logger.info('使用平面图生成路网: %s', image_path)
            network_data = generator.generate_from_floorplan(image_path, seats_data)
        else:
            # 无平面图：仅根据座位坐标生成简易路网
            logger.info('无平面图，使用座位坐标生成简易路网，座位数: %d', len(seats_data))
            width = floor.floor_plan_width or 800
            height = floor.floor_plan_height or 600
            network_data = generator.generate_from_seats_only(seats_data, width, height)
        logger.info('路网生成完成: %d 节点, %d 边',
                    len(network_data.get('nodes', {})),
                    len(network_data.get('edges', [])))
    except ValueError as e:
        return api_response(None, f'路网生成失败：{e}', 400)
    except AttributeError as e:
        logger.error('路网生成依赖缺失: %s', e)
        return api_response(None, '路网生成失败：缺少 opencv-contrib-python 依赖，请执行 pip install opencv-contrib-python', 500)
    except Exception as e:
        logger.exception('路网生成异常')
        return api_response(None, f'路网生成失败：{e}', 500)

    # 确保目录存在
    os.makedirs(os.path.join(app.root_path, 'data', 'networks'), exist_ok=True)
    network_path = os.path.join(app.root_path, 'data', 'networks', f'floor_{floor_id}.json')
    RoadNetwork.from_dict(network_data).save(network_path)
    floor.road_network_path = network_path
    db.session.commit()
    navigation_service.load_network(floor_id, network_path)

    try:
        os.makedirs(os.path.join(app.root_path, 'data', 'overlays'), exist_ok=True)
        overlay_path = os.path.join(app.root_path, 'data', 'overlays', f'floor_{floor_id}_preview.jpg')
        generator.generate_floor_overlay(image_path, network_data, overlay_path)
    except Exception as e:
        logger.warning('路网预览图生成失败（不影响路网）: %s', e)

    return api_response({
        'floor_id': floor_id, 'network': network_data,
        'preview_url': f'/data/overlays/floor_{floor_id}_preview.jpg',
        'node_count': len(network_data.get('nodes', {})),
        'edge_count': len(network_data.get('edges', [])),
    }, '路网生成成功')


@app.route('/api/admin/network/refine', methods=['POST'])
@admin_required
def refine_network():
    """应用管理员的拖拽/增删等微调结果，更新路网"""
    data = request.get_json()
    floor_id = data['floor_id']
    adjustments = data.get('adjustments', [])
    floor = Floor.query.get_or_404(floor_id)

    if not floor.road_network_path:
        return api_response(None, '路网数据不存在', 404)
    network = RoadNetwork.load(floor.road_network_path)
    if not network:
        return api_response(None, '路网加载失败', 500)

    generator = RoadNetworkGenerator()
    network_data = generator.refine_network(network.to_dict(), adjustments)
    RoadNetwork.from_dict(network_data).save(floor.road_network_path)
    navigation_service.load_network(floor_id, floor.road_network_path)

    return api_response({
        'node_count': len(network_data.get('nodes', {})),
        'edge_count': len(network_data.get('edges', [])),
    }, '路网更新成功')


@app.route('/api/admin/network/<int:floor_id>', methods=['GET'])
def get_network(floor_id):
    """获取指定楼层的路网数据"""
    floor = Floor.query.get_or_404(floor_id)
    if not floor.road_network_path or not os.path.exists(floor.road_network_path):
        return api_response(None, '路网数据不存在', 404)
    network = RoadNetwork.load(floor.road_network_path)
    if not network:
        return api_response(None, '路网加载失败', 500)
    return api_response(network.to_dict())


@app.route('/api/admin/network/save-manual', methods=['POST'])
@admin_required
def save_manual_network():
    """保存手动绘制的路网"""
    data = request.get_json()
    floor_id = data['floor_id']
    network_data = data.get('network', {})
    floor = Floor.query.get_or_404(floor_id)

    os.makedirs(os.path.join(app.root_path, 'data', 'networks'), exist_ok=True)
    network_path = os.path.join(app.root_path, 'data', 'networks', f'floor_{floor_id}.json')
    RoadNetwork.from_dict(network_data).save(network_path)
    floor.road_network_path = network_path
    db.session.commit()
    navigation_service.load_network(floor_id, network_path)

    return api_response(network_data, '路网已保存')


# ---------------------------------------------------------------------------
# API: 平面图上传
# ---------------------------------------------------------------------------


@app.route('/api/upload', methods=['POST'])
def upload_floor_plan():
    """上传平面图：保存文件并返回图片尺寸信息"""
    if 'file' not in request.files:
        return api_response(None, '请选择文件', 400)
    file = request.files['file']
    if file.filename == '':
        return api_response(None, '文件名为空', 400)

    import cv2
    file_id = str(uuid.uuid4())
    filename = secure_filename(file.filename)
    original_path = os.path.join(Config.UPLOAD_FOLDER, f'{file_id}_{filename}')
    file.save(original_path)

    img = cv2.imread(original_path)
    if img is None:
        return api_response(None, '无法读取图像文件', 400)

    height, width = img.shape[:2]
    return api_response({
        'session_id': str(uuid.uuid4()),
        'file_path': original_path,
        'file_url': f'/uploads/{file_id}_{filename}',
        'image_info': {
            'width': width, 'height': height,
            'channels': img.shape[2] if len(img.shape) > 2 else 1,
        },
    })


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """提供上传文件的静态访问（头像/平面图等）"""
    return send_from_directory(Config.UPLOAD_FOLDER, filename)


@app.route('/data/<path:filename>')
def data_file(filename):
    """提供 data 目录（路网JSON/叠加预览图等）的静态访问"""
    return send_from_directory(os.path.join(app.root_path, 'data'), filename)


# ---------------------------------------------------------------------------
# API: 系统配置
# ---------------------------------------------------------------------------


@app.route('/api/admin/config', methods=['GET', 'PUT'])
@admin_required
def system_config():
    """查看 / 更新系统配置（锁定参数、AI权重、传感器间隔等）"""
    if request.method == 'GET':
        return api_response({
            'lock_m_default': Config.LOCK_M_DEFAULT,
            'lock_n_default': Config.LOCK_N_DEFAULT,
            'lock_t_default': Config.LOCK_T_DEFAULT,
            'lock_m_range': Config.LOCK_M_RANGE,
            'lock_n_range': Config.LOCK_N_RANGE,
            'lock_t_range': Config.LOCK_T_RANGE,
            'ai_weights': Config.AI_WEIGHTS,
            'sensor_scan_interval': Config.SENSOR_SCAN_INTERVAL,
        })
    data = request.get_json()
    for key in data:
        if hasattr(Config, key.upper()):
            setattr(Config, key.upper(), data[key])
    return api_response(None, '配置已更新')


# ---------------------------------------------------------------------------
# API: 传感器模拟器控制
# ---------------------------------------------------------------------------


@app.route('/api/admin/simulator/start', methods=['POST'])
@admin_required
def start_simulator():
    """启动传感器模拟器（后台线程随机上报红外数据）"""
    data = request.get_json() or {}
    seat_count = data.get('seat_count', 50)
    interval = data.get('interval', Config.SENSOR_SCAN_INTERVAL)

    global sensor_simulator
    sensor_simulator = SensorSimulator(seat_count=seat_count, scan_interval=interval)

    def sensor_callback(seat_id, ir_front, ir_back):
        """模拟器回调：把红外数据写入座位并更新状态，通过 WebSocket 推送前端"""
        with app.app_context():
            seat = Seat.query.get(seat_id)
            if seat:
                seat.ir_front = ir_front
                seat.ir_back = ir_back
                both = ir_front == 1 and ir_back == 1
                if both and seat.status == 'free':
                    seat.status = 'occupied'
                    seat.occupied_since = datetime.utcnow()
                    seat.consecutive_empty = 0
                elif not both:
                    seat.consecutive_empty += 1
                    if seat.consecutive_empty >= 2 and seat.status == 'occupied':
                        seat.status = 'free'
                        seat.current_user_id = None
                        seat.occupied_since = None
                db.session.commit()
                socketio.emit('seat_update', {
                    'seat_id': seat_id, 'status': seat.status,
                    'ir_front': ir_front, 'ir_back': ir_back,
                })

    sensor_simulator.set_callback(sensor_callback)
    sensor_simulator.start()
    return api_response({'seat_count': seat_count, 'interval': interval}, '模拟器已启动')


@app.route('/api/admin/simulator/stop', methods=['POST'])
@admin_required
def stop_simulator():
    """停止传感器模拟器"""
    sensor_simulator.stop()
    return api_response(None, '模拟器已停止')


@app.route('/api/admin/simulator/occupy', methods=['POST'])
@admin_required
def simulate_occupy():
    """手动模拟指定座位占用/释放（用于演示与联调）"""
    data = request.get_json()
    seat_id = data.get('seat_id')
    occupied = data.get('occupied', True)
    sensor_simulator.simulate_occupancy(seat_id, occupied)
    return api_response(None, f'座位{seat_id} {"占用" if occupied else "释放"}模拟已触发')


# ---------------------------------------------------------------------------
# 初始化数据库
# ---------------------------------------------------------------------------


def init_database():
    """初始化数据库：建表，并首次创建默认超级管理员 admin/admin123"""
    with app.app_context():
        db.create_all()
        # 仅创建超级管理员（首次）
        if User.query.filter_by(role='super_admin').count() > 0:
            return
        from werkzeug.security import generate_password_hash
        admin = User(
            student_id='admin', name='系统管理员', role='super_admin',
            is_approved=True, password_hash=generate_password_hash('admin123'))
        db.session.add(admin)
        db.session.commit()
        logger.info('超级管理员: admin / admin123')


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _qu_lou_ti_kou_jie_dian(from_floor_id, to_floor_id):
    """获取跨层导航用的楼梯口节点映射 {楼层id: 楼梯节点id}"""
    lou_ti_kou_jie_dian = {}
    for lou_ceng_id in [from_floor_id, to_floor_id]:
        floor = Floor.query.get(lou_ceng_id)
        if floor and floor.road_network_path:
            network = RoadNetwork.load(floor.road_network_path)
            if network:
                for jie_dian_id, jie_dian_shu_ju in network.nodes.items():
                    if jie_dian_shu_ju.get('type') == 'stair':
                        lou_ti_kou_jie_dian[lou_ceng_id] = jie_dian_id
                        break
        if lou_ceng_id not in lou_ti_kou_jie_dian and floor and floor.road_network_path:
            network = RoadNetwork.load(floor.road_network_path)
            if network and network.nodes:
                lou_ti_kou_jie_dian[lou_ceng_id] = list(network.nodes.keys())[0]
    return lou_ti_kou_jie_dian


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    init_database()
    # 确保 127.0.0.1 和局域网 IP 均可访问：
    # 方式1: python app.py          → 监听 127.0.0.1:5000
    # 方式2: python app.py 0.0.0.0  → 监听所有网卡
    # 端口 5800 避免与 Windows 系统服务冲突
    import sys
    bind_host = sys.argv[1] if len(sys.argv) > 1 else '127.0.0.1'
    bind_port = int(sys.argv[2]) if len(sys.argv) > 2 else 5800
    logger.info(f'服务启动 http://{bind_host}:{bind_port}')
    if bind_host == '0.0.0.0':
        import socket
        hostname = socket.gethostbyname(socket.gethostname())
        logger.info(f'局域网访问 http://{hostname}:{bind_port}')
    socketio.run(app, debug=os.getenv('DEBUG', 'True').lower() == 'true',
                 host=bind_host, port=bind_port, allow_unsafe_werkzeug=True)

"""
智能选座与导航一体化系统 - 后端主入口
基于物联网感知的公共空间智能选座与导航系统
"""
import os
import io
import sys
import shutil
import secrets
import uuid
import json
import time
import logging
import threading
from datetime import datetime, timedelta, timezone
from functools import wraps
from sqlalchemy import update, text
from urllib.parse import quote

import qrcode

from flask import (
    Flask, request, jsonify, render_template,
    session, redirect, url_for, send_from_directory, send_file
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
from models.sensor_device import SensorDevice
from models.school import School
from utils import (
    locking, validate_return, BehaviorTracker,
    ImagePreprocessor, RecommendationEngine,
    RoadNetwork, PathFinder, NavigationService,
    SensorSimulator, RoadNetworkGenerator,
    get_llm, reload_llm,
    get_user_ai, get_admin_ai, reset_ai_services, terminal_brief,
    build_seat_snapshot,
)

load_dotenv()

# ---------------------------------------------------------------------------
# 自动建图模块（view/auto_mapping.py）加载
# 将 view 目录加入 sys.path，保证 auto_mapping 内 from vitalframe import ... 可解析
# ---------------------------------------------------------------------------
VIEW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'view')
VIEW_OUTPUTS_DIR = os.path.join(VIEW_DIR, 'outputs')
if VIEW_DIR not in sys.path:
    sys.path.insert(0, VIEW_DIR)

try:
    import importlib
    _auto_mapping_mod = importlib.import_module('auto_mapping')
    _map_process_video = _auto_mapping_mod.process_video
    _map_process_frames = _auto_mapping_mod.process_frames
    _map_process_image_list = _auto_mapping_mod.process_image_list
    _AUTO_MAPPING_AVAILABLE = True
except Exception as _map_import_err:
    logger.warning('自动建图模块加载失败: %s', _map_import_err)
    _AUTO_MAPPING_AVAILABLE = False

# ---------------------------------------------------------------------------
# App 初始化
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config.from_object(Config)

# 没有显式 SECRET_KEY 时生成一个持久化密钥，避免多 worker 间 session 互踢。
if not os.getenv('SECRET_KEY'):
    os.makedirs(app.instance_path, exist_ok=True)
    _secret_path = os.path.join(app.instance_path, 'secret_key')
    if os.path.exists(_secret_path):
        with open(_secret_path, 'r', encoding='utf-8') as f:
            app.config['SECRET_KEY'] = f.read().strip()
    else:
        app.config['SECRET_KEY'] = secrets.token_hex(32)
        with open(_secret_path, 'w', encoding='utf-8') as f:
            f.write(app.config['SECRET_KEY'])

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
_redis_client = None
_redis_message_queue = None
try:
    import redis as redis_lib
    _redis_client = redis_lib.Redis(
        host=Config.REDIS_HOST, port=Config.REDIS_PORT, db=Config.REDIS_DB,
        password=Config.REDIS_PASSWORD, decode_responses=True,
        socket_connect_timeout=1.0, socket_timeout=1.0,
    )
    _redis_client.ping()
    if Config.REDIS_PASSWORD:
        _redis_message_queue = (
            f'redis://:{quote(Config.REDIS_PASSWORD, safe="")}'
            f'@{Config.REDIS_HOST}:{Config.REDIS_PORT}/{Config.REDIS_DB}'
        )
    else:
        _redis_message_queue = (
            f'redis://{Config.REDIS_HOST}:{Config.REDIS_PORT}/{Config.REDIS_DB}'
        )
except Exception as e:
    _redis_client = None
    logger.warning('Redis 不可用，SocketIO 将使用单进程模式: %s', e)
socketio.init_app(
    app,
    cors_allowed_origins=cors_origins if cors_origins != '*' else '*',
    message_queue=_redis_message_queue,
)

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
    user = _load_current_user()
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

_RUNTIME_CONFIG_FILE = os.path.join(app.root_path, 'data', 'system_config.json')


def _load_runtime_config():
    """启动时加载管理员上次保存的运行期配置。"""
    if not os.path.exists(_RUNTIME_CONFIG_FILE):
        return
    try:
        with open(_RUNTIME_CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        logger.warning('运行期配置文件读取失败，使用默认配置')
        return
    for key, value in data.items():
        upper_key = key.upper()
        if hasattr(Config, upper_key):
            setattr(Config, upper_key, value)
    if hasattr(Config, 'AI_WEIGHTS'):
        try:
            recommendation_engine.update_weights(Config.AI_WEIGHTS)
        except ValueError:
            pass
    sensor_simulator.scan_interval = Config.SENSOR_SCAN_INTERVAL


_load_runtime_config()

# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def get_or_create_behavior_tracker(user_id: str) -> BehaviorTracker:
    """获取用户的全局行为追踪器（不存在则创建）"""
    if user_id not in behavior_trackers:
        tracker = None
        if _redis_client:
            try:
                raw = _redis_client.get(_behavior_key(user_id))
                if raw:
                    tracker = BehaviorTracker.from_persist_dict(json.loads(raw))
            except Exception:
                logger.warning('从 Redis 恢复行为数据失败: user=%s', user_id)
        if not tracker:
            tracker = BehaviorTracker(user_id=user_id)
        behavior_trackers[user_id] = tracker
    return behavior_trackers[user_id]


def _behavior_key(user_id: str) -> str:
    return f'behavior_tracker:{user_id}'


def _save_behavior_tracker(tracker: BehaviorTracker):
    if not _redis_client:
        return
    try:
        _redis_client.set(
            _behavior_key(tracker.user_id),
            json.dumps(tracker.to_persist_dict(), ensure_ascii=False),
            ex=7 * 24 * 3600,
        )
    except Exception:
        logger.warning('保存行为数据到 Redis 失败: user=%s', tracker.user_id)


def _load_current_user():
    """从 session 中加载当前用户；用户不存在或已停用时返回 None。"""
    user_id = session.get('user_id')
    if not user_id:
        return None
    return db.session.get(User, user_id)


def _is_admin() -> bool:
    """判断当前登录用户是否具备管理员权限。"""
    user = _load_current_user()
    if not user or not user.is_active:
        return False
    if user.role == 'admin' and not user.is_approved:
        return False
    return user.role in ('admin', 'super_admin')


def api_response(data=None, message='success', code=200):
    """统一 API 返回格式：{code, message, data}"""
    return jsonify({'code': code, 'message': message, 'data': data}), code


def _normalize_utc(value: datetime) -> datetime:
    """把带时区的时间统一转成无时区的 UTC 时间，避免与 datetime.utcnow() 混用。"""
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _create_reservation(user_id, seat_id, start_time, end_time):
    """按时间段创建预约。

    预约成功时**不立即占用座位**：座位在预约开始时间到点后，
    由后台任务 _run_reservation_transition 自动置为占用（变红），
    时间段结束后自动释放。
    """
    user = db.session.get(User, user_id)
    if not user:
        return None, '用户不存在'

    start_time = _normalize_utc(start_time)
    end_time = _normalize_utc(end_time)
    now = datetime.utcnow()
    if end_time <= start_time:
        return None, '结束时间必须晚于开始时间'
    # 禁止预约已过去的时间（前端时段按钮也已置灰，此处为后端兜底校验）
    # 只能预约未来时间段：已开始/已过去的时段一律拒绝
    if start_time < now:
        return None, '不能预约已过去的时间'

    seat = db.session.get(Seat, seat_id)
    if not seat or not seat.is_active:
        return None, '座位不存在'

    # 同一座位同时间段只允许一个预约（时段冲突检查）
    overlap = Reservation.query.filter(
        Reservation.seat_id == seat_id,
        Reservation.status == 'pending',
        Reservation.start_time < end_time,
        Reservation.end_time > start_time,
    ).first()
    if overlap:
        return None, '该时段已被预约'

    # 每人最多同时预约 2 个未开始的时间段
    active_count = Reservation.query.filter(
        Reservation.user_id == user_id,
        Reservation.status == 'pending',
        Reservation.end_time > now,
    ).count()
    if active_count >= 2:
        return None, '每人最多同时预约 2 个时间段，请先使用或取消已有预约'

    reservation = Reservation(
        user_id=user_id,
        seat_id=seat_id,
        building_id=seat.floor.building_id,
        start_time=start_time,
        end_time=end_time,
        qr_token=uuid.uuid4().hex[:16],
        status='pending',
    )
    db.session.add(reservation)
    try:
        db.session.commit()
        db.session.expire_all()
        return reservation, None
    except Exception:
        db.session.rollback()
        return None, '预约失败'


def login_required(f):
    """登录校验装饰器：未登录时 JSON 请求返回 401，页面请求跳转登录页"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = _load_current_user()
        if not user or not user.is_active:
            session.clear()
            if request.is_json or request.path.startswith('/api/'):
                return api_response(None, '请先登录', 401)
            return redirect(url_for('login', next=request.path))
        session['role'] = user.role
        session['name'] = user.name
        session['avatar_url'] = user.avatar_url or ''
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """管理员权限校验装饰器：仅 admin / super_admin 可访问"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = _load_current_user()
        if not user or not user.is_active:
            session.clear()
            if request.is_json or request.path.startswith('/api/'):
                return api_response(None, '请先登录', 401)
            return redirect(url_for('login', next=request.path))
        if user.role == 'admin' and not user.is_approved:
            session['role'] = user.role
            if request.is_json or request.path.startswith('/api/'):
                return api_response(None, '管理员账号正在审核中', 403)
            return redirect(url_for('index'))
        if user.role not in ('admin', 'super_admin'):
            if request.is_json or request.path.startswith('/api/'):
                return api_response(None, '权限不足', 403)
            return redirect(url_for('index'))
        session['role'] = user.role
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
        if not user or not user.is_active:
            return render_template('login.html', error="用户名或密码错误！")
        if user.role == 'admin' and not user.is_approved:
            return render_template('login.html', error="管理员账号正在审核中")
        if check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['role'] = user.role
            session['username'] = user.student_id
            session['name'] = user.name
            session['avatar_url'] = user.avatar_url or ''
            user.last_login_at = datetime.utcnow()
            db.session.commit()
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
    if not user or not user.is_active:
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
    user.last_login_at = datetime.utcnow()
    db.session.commit()

    return api_response({
        'user_id': user.id,
        'name': user.name,
        'role': user.role,
        'student_id': user.student_id,
    }, '登录成功')


REGISTER_ROLES = {
    'student':      {'db_role': 'student', 'need_school': True,
                     'approved': True,  'label': '学生'},
    'user':         {'db_role': 'student', 'need_school': False,
                     'approved': True,  'label': '普通用户'},
    'school_admin': {'db_role': 'admin',   'need_school': True,
                     'approved': False, 'label': '学校管理员'},
    'admin':        {'db_role': 'admin',   'need_school': False,
                     'approved': False, 'label': '管理员'},
}


def _resolve_register_school(data):
    """确定注册归属学校，返回 (school, created, error)。

    支持两种方式：
      * school_id   从下拉里选已有学校
      * school_name 手动输入校名；已存在则复用（忽略大小写），不存在则新建
    """
    sid = data.get('school_id')
    name = str(data.get('school_name') or '').strip()

    if sid not in (None, '', 0, '0'):
        try:
            sc = db.session.get(School, int(sid))
        except (TypeError, ValueError):
            return None, False, '学校参数无效'
        if not sc or not sc.is_active:
            return None, False, '所选学校不存在或已停用'
        return sc, False, None

    if not name:
        return None, False, '请填写或选择所属学校'
    if len(name) > 100:
        return None, False, '学校名称过长（上限 100 字）'

    sc = School.query.filter(db.func.lower(School.name) == name.lower()).first()
    if sc:
        if not sc.is_active:
            return None, False, '该学校已停用，请联系管理员'
        return sc, False, None

    # 手动输入了一个新学校 -> 直接创建（管理员后续可改名/停用）
    sc = School(name=name, is_active=True)
    db.session.add(sc)
    db.session.flush()
    logger.info('注册时新建学校：%s (id=%s)', name, sc.id)
    return sc, True, None


@app.route('/api/auth/register', methods=['POST'])
# 注册身份映射（叠加式：不改数据库枚举，用 role + school_id 组合派生）
#   key          前端提交的 role
#   db_role      写入 User.role
#   need_school  是否必须填所属学校
#   approved     是否免审核
#   label        中文名（用于提示语）
def api_register():
    """用户注册。

    注册身份分四种（不新增数据库枚举，用 role + school_id 组合派生）：
      学生       student      + 必须填学校，直接通过
      普通用户   student      + 不填学校，直接通过
      学校管理员 admin        + 必须填学校，需审核
      管理员     admin        + 不填学校，需审核
    学校既可从下拉选择，也可**手动输入**校名；输入的是新学校时自动创建。
    """
    data = request.get_json()
    student_id = data.get('student_id', '').strip()
    name = data.get('name', '').strip()
    password = data.get('password', '')
    confirm = data.get('confirm_password', '')
    role_key = data.get('role', 'student') or 'student'

    if not student_id or not name or not password:
        return api_response(None, '请填写完整信息', 400)
    if len(password) < 6:
        return api_response(None, '密码至少6位', 400)
    if password != confirm:
        return api_response(None, '两次输入的密码不一致', 400)

    # 角色白名单校验：防止恶意用户注册为管理员
    spec = REGISTER_ROLES.get(role_key)
    if not spec:
        return api_response(None, '无效的角色类型', 400)

    # 仅「学生 / 学校管理员」需要归属学校
    school, school_created = None, False
    if spec['need_school']:
        school, school_created, err = _resolve_register_school(data)
        if err:
            return api_response(None, err, 400)

    exist = User.query.filter_by(student_id=student_id).first()
    if exist:
        return api_response(None, '该账号已注册', 409)

    user = User(
        student_id=student_id,
        school_id=school.id if school else None,
        name=name,
        role=spec['db_role'],
        password_hash=generate_password_hash(password),
        # 管理员类需审核，学生/普通用户直接通过（沿用原有规则）
        is_approved=spec['approved'],
        # 登记注册身份（存 JSON，不改表结构）；角色徽章以此为准，
        # 避免"有学校就被当成学生"这类由数据属性反推身份的误判
        preferences={'user_type': role_key},
    )
    db.session.add(user)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return api_response(None, '注册失败，账号可能已存在', 409)

    msg = ('注册成功，请登录' if spec['approved']
           else '注册成功，%s账号需等待审核后登录' % spec['label'])
    if school_created:
        msg += '（已新建学校「%s」）' % school.name
    return api_response({
        'user_id': user.id,
        'name': user.name,
        'role': user.role,
        'role_label': spec['label'],
        'school_id': school.id if school else None,
        'school_name': school.name if school else None,
        'school_created': school_created,
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
                           current_building_id=building_id, current_floor_id=floor_id,
                           is_admin=session.get('role') in ('admin', 'super_admin'))


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
                           target_seat=target_seat, reservations=reservations,
                           checkin_qr_enabled=Config.CHECKIN_QR_ENABLED)


@app.route('/reservation/do', methods=['POST'])
@login_required
def do_reserve():
    """表单方式提交预约：占用座位并生成预约记录"""
    seat_id = request.form.get('seat_id', type=int)
    duration = request.form.get('duration', 2, type=int)
    if not seat_id or duration <= 0:
        return redirect(url_for('reservation_page'))
    now = datetime.utcnow()
    _, error = _create_reservation(
        session['user_id'], seat_id, now, now + timedelta(hours=duration)
    )
    if error:
        return redirect(url_for('reservation_page'))
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
        # 仅当座位确实被该预约持有（预约时段内占用）时才释放
        if seat and seat.current_user_id == reservation.user_id:
            seat.status = 'free'
            seat.current_user_id = None
            seat.occupied_since = None
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


@app.route('/admin/hardware')
@admin_required
def admin_hardware():
    """硬件 / 传感器调试面板页（模拟器控制、每座位传感器、手动模拟上报）"""
    return render_template('admin/hardware.html')


@app.route('/admin/seats-qrcodes')
@admin_required
def admin_seats_qrcodes():
    """座位二维码打印页：列出各场所/楼层/座位二维码，供打印后粘贴到桌上"""
    buildings = Building.query.filter_by(is_active=True).all()
    groups = []
    for b in buildings:
        for floor in b.floors.filter(Floor.is_active == True).order_by(Floor.floor_number).all():
            seats = floor.seats.filter(Seat.is_active == True).order_by(Seat.seat_label).all()
            if seats:
                groups.append({
                    'building': b.name,
                    'floor': floor.name or f'{floor.floor_number}F',
                    'seats': seats,
                })
    return render_template('admin/seats_qrcodes.html', groups=groups)


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


# ---------------------------------------------------------------------------
# API: 学校（学校模式的顶层归属）
# ---------------------------------------------------------------------------


def school_admin_required(f):
    """要求「管理员 + 已归属某学校」。

    批量导入学生本质上是在为**某所学校**建账号，因此非学校管理员
    （如未绑定学校的普通管理员、超管代管场景）不应看到也不应调用。
    超管若确实要导入，需通过 school_id 显式指定目标学校 ——
    为此超管放行，但仍必须显式传 school_id（在接口内校验）。
    """
    from functools import wraps

    @wraps(f)
    def wrapper(*args, **kwargs):
        user = _load_current_user()
        if not user or user.role not in ('admin', 'super_admin'):
            return api_response(None, '需要管理员权限', 403)
        if user.role == 'admin' and not user.school_id:
            return api_response(
                None, '该功能属于「学校管理员」，当前账号未归属任何学校', 403)
        return f(*args, **kwargs)
    return wrapper


def _mask_secret(value, head=4, tail=4):
    """密钥掩码：只回传首尾少量字符，绝不回传明文。"""
    v = str(value or '')
    if not v:
        return ''
    if len(v) <= head + tail:
        return '*' * len(v)
    return v[:head] + '*' * (len(v) - head - tail) + v[-tail:]


def _view_school_id(user=None):
    """当前上下文应限定的学校 id；返回 None 表示「不限学校」。

    规则（按需求确认）：
      * 未登录        -> None：注册页需要看学校下拉列表等公共信息
      * 超级管理员    -> None：需求 5B，超管可跨校查看
      * 管理员/学生   -> user.school_id
      * 已登录但未绑定学校（历史数据）-> None（不限），
        这样不会把升级前的老数据挡在外面；生产环境可改为强制绑定。
    """
    try:
        user = user or _load_current_user()
    except Exception:
        return None
    if not user:
        return None
    if getattr(user, 'role', None) == 'super_admin':
        return None
    return getattr(user, 'school_id', None) or None


def _apply_school_filter(query, model, user=None):
    """按当前用户所属学校过滤查询（None 则不过滤）。"""
    sid = _view_school_id(user)
    if sid is None:
        return query
    return query.filter(model.school_id == sid)


# ---------------------------------------------------------------------------
# API: 学生批量导入（管理员上传表格 -> 自动注册）
# ---------------------------------------------------------------------------


@app.route('/api/admin/students', methods=['GET'])
@school_admin_required
@admin_required
def admin_list_students():
    """学生列表（按当前用户所属学校收口；超管可跨校）。"""
    q = request.args.get('q', '').strip()
    role = request.args.get('role', 'student')
    page = max(int(request.args.get('page', 1) or 1), 1)
    size = min(max(int(request.args.get('size', 50) or 50), 1), 500)

    query = User.query
    if role in ('student', 'admin', 'super_admin'):
        query = query.filter(User.role == role)
    sid = _view_school_id()
    if sid is not None:
        query = query.filter(User.school_id == sid)
    if q:
        query = query.filter(db.or_(User.student_id.ilike(f'%{q}%'),
                                    User.name.ilike(f'%{q}%')))
    total = query.count()
    rows = (query.order_by(User.id).offset((page - 1) * size).limit(size).all())
    return api_response({
        'total': total, 'page': page, 'size': size,
        'students': [u.to_dict() for u in rows],
    })


@app.route('/api/admin/students/import/template', methods=['GET'])
@school_admin_required
@admin_required
def download_student_template():
    """下载导入模板（xlsx）。"""
    from utils.student_import import build_template_xlsx
    data = build_template_xlsx()
    from flask import send_file
    return send_file(
        io.BytesIO(data),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='学生导入模板.xlsx')


@app.route('/api/admin/students/import', methods=['POST'])
@school_admin_required
@admin_required
def import_students_api():
    """上传 Excel/CSV 批量创建学生账号。

    表单字段：
      file       必填，.xlsx / .csv
      school_id  可选，默认取当前管理员的学校（超管必须显式指定）
    """
    from utils.student_import import parse_rows, import_students, ImportError_

    if 'file' not in request.files:
        return api_response(None, '请选择要上传的表格文件', 400)
    f = request.files['file']
    if not f or not f.filename:
        return api_response(None, '请选择要上传的表格文件', 400)

    # 目标学校：显式传参优先，否则用当前管理员的学校
    sid_raw = request.form.get('school_id')
    target_school = None
    if sid_raw not in (None, '', '0'):
        try:
            target_school = int(sid_raw)
        except (TypeError, ValueError):
            return api_response(None, 'school_id 参数无效', 400)
    else:
        target_school = _view_school_id()
    if not target_school:
        return api_response(None, '无法确定导入到哪所学校，请显式指定 school_id', 400)
    if not db.session.get(School, target_school):
        return api_response(None, '指定的学校不存在', 400)

    content = f.read()
    if not content:
        return api_response(None, '上传的文件是空的', 400)
    max_mb = 8
    if len(content) > max_mb * 1024 * 1024:
        return api_response(None, f'文件过大（上限 {max_mb}MB）', 400)

    try:
        rows, file_errors = parse_rows(f.filename, content)
    except ImportError_ as e:
        return api_response(None, str(e), 400)

    if not rows:
        return api_response({'summary': {'created': 0, 'skipped': 0,
                                         'conflict': 0, 'failed': 0},
                             'file_errors': file_errors},
                            file_errors[0] if file_errors else '表格里没有数据行', 400)

    try:
        report = import_students(rows, target_school)
    except ImportError_ as e:
        return api_response(None, str(e), 400)

    report['file_errors'] = file_errors
    s = report['summary']
    msg = ('导入完成：新增 %d，跳过 %d，冲突 %d，失败 %d'
           % (s['created'], s['skipped'], s['conflict'], s['failed']))
    logger.info('学生导入：学校=%s %s', target_school, msg)
    return api_response(report, msg)


# ---------------------------------------------------------------------------
# API: 室外导航（地图配置 + 目的地列表）
# ---------------------------------------------------------------------------


@app.route('/api/nav/config', methods=['GET'])
def nav_config():
    """前端加载地图 SDK 所需的配置。

    地图 JS API 的 key 属于「会暴露在前端」的凭证（高德/百度皆如此），
    但仍要求登录后再下发，避免被匿名抓取滥用配额。
    """
    user = _load_current_user()
    provider = getattr(Config, 'NAV_MAP_PROVIDER', 'amap')
    key = getattr(Config, 'NAV_MAP_KEY', '') if user else ''
    code = getattr(Config, 'NAV_MAP_SECURITY_CODE', '') if user else ''
    return api_response({
        'provider': provider,
        'key': key or '',
        'security_code': code or '',
        'has_key': bool(key),
        'fallback_enabled': getattr(Config, 'NAV_FALLBACK_ENABLED', True),
        'logged_in': bool(user),
    })


@app.route('/api/nav/destinations', methods=['GET'])
def nav_destinations():
    """室外导航目的地：带经纬度的建筑（按学校收口）。

    仅返回已配置坐标的建筑 —— 没坐标的无法做室外导航。
    """
    query = Building.query.filter(
        Building.is_active == True,  # noqa: E712
        Building.lat.isnot(None),
        Building.lng.isnot(None),
    )
    query = _apply_school_filter(query, Building)
    with_coords = query.order_by(Building.name).all()

    # 同时告诉前端还有多少建筑没配坐标（便于提示管理员）
    q_all = Building.query.filter(Building.is_active == True)  # noqa: E712
    q_all = _apply_school_filter(q_all, Building)
    total = q_all.count()

    return api_response({
        'destinations': [{
            'id': b.id,
            'name': b.name,
            'alias': b.alias,
            'region': b.region,
            'address': b.address,
            'lat': b.lat,
            'lng': b.lng,
            'school_id': b.school_id,
            'school_name': b.school.name if b.school else None,
        } for b in with_coords],
        'total_buildings': total,
        'missing_coords': max(total - len(with_coords), 0),
    })


@app.route('/outdoor')
def outdoor_nav_page():
    """室外导航页（从当前位置导航到建筑）"""
    return render_template('outdoor.html')


@app.route('/api/schools', methods=['GET'])
def list_schools():
    """学校列表。

    公开可读：注册页需要它渲染「选择学校」下拉框，
    且只暴露学校名称/区域等非敏感信息。
    """
    with_stats = request.args.get('with_stats') == '1'
    q = request.args.get('q', '').strip()
    query = School.query.filter_by(is_active=True)
    if q:
        query = query.filter(db.or_(School.name.ilike(f'%{q}%'),
                                    School.code.ilike(f'%{q}%'),
                                    School.region.ilike(f'%{q}%')))
    schools = query.order_by(School.name).all()

    # 带统计的列表仅管理员可见（含用户数等）
    if with_stats:
        user = _load_current_user()
        if not user or user.role not in ('admin', 'super_admin'):
            with_stats = False
    return api_response([x.to_dict(with_stats=with_stats) for x in schools])


@app.route('/api/schools', methods=['POST'])
@admin_required
def create_school():
    """新建学校（管理员）。"""
    data = request.get_json(silent=True) or {}
    name = str(data.get('name', '')).strip()
    if not name:
        return api_response(None, '学校名称不能为空', 400)
    if School.query.filter_by(name=name).first():
        return api_response(None, f'学校「{name}」已存在', 400)
    code = str(data.get('code', '')).strip() or None
    if code and School.query.filter_by(code=code).first():
        return api_response(None, f'学校编码「{code}」已被占用', 400)

    school = School(
        name=name, code=code,
        region=str(data.get('region', '')).strip() or None,
        address=str(data.get('address', '')).strip() or None,
        description=str(data.get('description', '')).strip() or None,
    )
    for k in ('lat', 'lng'):
        v = data.get(k)
        if v not in (None, ''):
            try:
                setattr(school, k, float(v))
            except (TypeError, ValueError):
                return api_response(None, f'{k} 必须为数字', 400)
    db.session.add(school)
    db.session.commit()
    return api_response(school.to_dict(), '学校已创建')


@app.route('/api/schools/<int:school_id>', methods=['PUT'])
@admin_required
def update_school(school_id):
    """修改学校（管理员）。"""
    school = db.session.get(School, school_id)
    if not school:
        return api_response(None, '学校不存在', 404)
    data = request.get_json(silent=True) or {}
    if 'name' in data:
        name = str(data['name']).strip()
        if not name:
            return api_response(None, '学校名称不能为空', 400)
        dup = School.query.filter(School.name == name, School.id != school.id).first()
        if dup:
            return api_response(None, f'学校「{name}」已存在', 400)
        school.name = name
    if 'code' in data:
        code = str(data['code']).strip() or None
        if code:
            dup = School.query.filter(School.code == code, School.id != school.id).first()
            if dup:
                return api_response(None, f'学校编码「{code}」已被占用', 400)
        school.code = code
    for k in ('region', 'address', 'description'):
        if k in data:
            setattr(school, k, str(data[k]).strip() or None)
    for k in ('lat', 'lng'):
        if k in data:
            v = data[k]
            if v in (None, ''):
                setattr(school, k, None)
            else:
                try:
                    setattr(school, k, float(v))
                except (TypeError, ValueError):
                    return api_response(None, f'{k} 必须为数字', 400)
    if 'is_active' in data:
        school.is_active = bool(data['is_active'])
    db.session.commit()
    return api_response(school.to_dict(), '学校已更新')


@app.route('/api/schools/<int:school_id>', methods=['DELETE'])
@admin_required
def delete_school(school_id):
    """停用学校（保留数据，仅置 is_active=False）。"""
    school = db.session.get(School, school_id)
    if not school:
        return api_response(None, '学校不存在', 404)
    school.is_active = False
    db.session.commit()
    return api_response(None, f'学校「{school.name}」已停用')


@app.route('/api/search/venues', methods=['GET'])
def search_venues():
    """搜索场所（按名称/地址/区域模糊匹配）"""
    q = request.args.get('q', '').strip()
    if not q or len(q) < 1:
        return api_response([])

    query = Building.query.filter(
        Building.is_active == True,  # noqa: E712
        db.or_(
            Building.name.ilike(f'%{q}%'),
            Building.alias.ilike(f'%{q}%'),
            Building.region.ilike(f'%{q}%'),
            Building.address.ilike(f'%{q}%'),
        )
    )
    # 学校模式：登录用户只在所属学校范围内搜索（超管不限）
    query = _apply_school_filter(query, Building)
    results = query.order_by(Building.name).all()
    return api_response([b.to_dict() for b in results])


@app.route('/api/buildings', methods=['GET'])
def get_buildings():
    """获取建筑物列表（附带总座位数/空闲座位数统计）"""
    query = Building.query.filter_by(is_active=True)
    # 学校模式：只列出当前用户所属学校的建筑（超管不限）
    query = _apply_school_filter(query, Building)
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


def _parse_coord(value, name, lo, hi):
    """解析并校验经纬度；返回 (值, 错误信息)。空值 -> (None, None)。"""
    if value in (None, '', 'null'):
        return None, None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None, '%s 必须为数字' % name
    if not (lo <= v <= hi):
        return None, '%s 超出范围（%s ~ %s）' % (name, lo, hi)
    return v, None


def _building_payload(data, building=None):
    """把请求数据写入 building，返回错误信息（None 表示成功）。

    支持：name / alias / region / address / lat / lng / description / school_id
    """
    if 'name' in data:
        name = str(data.get('name') or '').strip()
        if not name:
            return '建筑物名称不能为空'
        building.name = name
    for f in ('alias', 'region', 'address', 'description'):
        if f in data:
            setattr(building, f, (str(data[f]).strip() or None) if data[f] is not None else None)

    for f, lo, hi in (('lat', -90, 90), ('lng', -180, 180)):
        if f in data:
            v, err = _parse_coord(data[f], f, lo, hi)
            if err:
                return err
            setattr(building, f, v)

    if 'school_id' in data:
        v = data.get('school_id')
        if v in (None, '', 0, '0'):
            building.school_id = None
        else:
            try:
                v = int(v)
            except (TypeError, ValueError):
                return 'school_id 必须为数字'
            if not db.session.get(School, v):
                return '指定的学校不存在'
            building.school_id = v
    return None


@app.route('/api/buildings', methods=['POST'])
@admin_required
def create_building():
    """创建建筑物（学校模式下默认归属当前管理员的学校）"""
    data = request.get_json() or {}
    building = Building(name='')
    err = _building_payload(data, building)
    if err:
        return api_response(None, err, 400)
    if not building.name:
        return api_response(None, '建筑物名称不能为空', 400)
    # 未显式指定学校时，默认落到当前管理员所属学校（超管可显式传 0 表示不限）
    if 'school_id' not in data:
        sid = _view_school_id()
        if sid is not None:
            building.school_id = sid
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
    """更新建筑物信息（含目标地点经纬度、所属学校）"""
    building = Building.query.get_or_404(building_id)
    data = request.get_json() or {}
    err = _building_payload(data, building)
    if err:
        return api_response(None, err, 400)
    db.session.commit()
    return api_response(building.to_dict(), '建筑物已更新')


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
    """更新座位信息（坐标/类型/红外/开关状态等）"""
    seat = Seat.query.get_or_404(seat_id)
    data = request.get_json()
    for field in ['seat_label', 'seat_type', 'x', 'y', 'width', 'height',
                  'rotation', 'ir_front', 'ir_back', 'ir_enabled',
                  'nearest_node_id', 'is_active']:
        if field in data:
            setattr(seat, field, data[field])
    # 管理员手动设置座位状态（标记异常 / 恢复正常等）
    if 'status' in data:
        new_status = data['status']
        if new_status not in ('free', 'occupied', 'locked', 'error'):
            return api_response(None, '无效的座位状态', 400)
        seat.status = new_status
        if new_status == 'error':
            seat.error_since = datetime.utcnow()
        else:
            seat.error_since = None
            if new_status == 'free':
                seat.current_user_id = None
                seat.occupied_since = None
                seat.lock_available_since = None
        socketio.emit('seat_update', {'seat_id': seat.id, 'status': seat.status})
    # 关闭座位时，若仍被占用/锁定，重置为空闲，避免"占用但已关闭"的矛盾状态
    if 'is_active' in data and not data['is_active'] and seat.status in ('occupied', 'locked'):
        seat.status = 'free'
        seat.current_user_id = None
        seat.occupied_since = None
        seat.lock_available_since = None
        socketio.emit('seat_update', {'seat_id': seat.id, 'status': 'free'})
    db.session.commit()
    return api_response(seat.to_dict())


@app.route('/api/admin/seats/ir', methods=['PUT'])
@admin_required
def set_all_seats_ir():
    """批量开启/关闭所有开放座位的红外传感器（总开关）"""
    data = request.get_json(silent=True) or {}
    ir_enabled = bool(data.get('ir_enabled', True))
    seats = Seat.query.filter_by(is_active=True).all()
    changed = 0
    for s in seats:
        if s.ir_enabled != ir_enabled:
            s.ir_enabled = ir_enabled
            changed += 1
    db.session.commit()
    for s in seats:
        socketio.emit('seat_update', {
            'seat_id': s.id, 'status': s.status, 'ir_enabled': s.ir_enabled,
        })
    action = '开启' if ir_enabled else '关闭'
    return api_response({'count': changed, 'ir_enabled': ir_enabled},
                        f'已{action} {changed} 个座位的红外')


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
    """获取座位列表（可按楼层/状态过滤；管理员可传 include_inactive=1 查看已关闭座位）"""
    query = Seat.query
    floor_id = request.args.get('floor_id', type=int)
    status = request.args.get('status')
    include_inactive = request.args.get('include_inactive') == '1'

    if status == 'inactive':
        query = query.filter_by(is_active=False)
    else:
        if not include_inactive:
            query = query.filter_by(is_active=True)
        if status:
            query = query.filter_by(status=status)
    if floor_id:
        query = query.filter_by(floor_id=floor_id)
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
    """红外交叉校验：两束同时遮挡 → 有人

    座位标识支持两种方式（ESP32 固件按需选用，见 DEMO/src/main.cpp 配置）：
    - seat_id:    数据库座位数字 ID（兼容原逻辑，优先）
    - seat_label: 座位标签（如 "A区-12"，与平面图一致）；同名标签跨楼层存在时
                  需携带 floor_id 消歧，否则返回 400 提示
    """
    data = request.get_json()
    seat_id = data.get('seat_id')
    ir_front = data.get('ir_front', 0)
    ir_back = data.get('ir_back', 0)

    seat = None
    if seat_id is not None:
        try:
            seat_id = int(seat_id)
        except (TypeError, ValueError):
            return api_response(None, 'seat_id 必须为数字', 400)
        seat = db.session.get(Seat, seat_id)
    else:
        label = str(data.get('seat_label', '')).strip()
        if not label:
            return api_response(None, 'seat_id 或 seat_label 不能为空', 400)
        query = Seat.query.filter_by(seat_label=label)
        floor_id = data.get('floor_id')
        if floor_id is not None:
            try:
                floor_id = int(floor_id)
            except (TypeError, ValueError):
                return api_response(None, 'floor_id 必须为数字', 400)
            query = query.filter_by(floor_id=floor_id)
        matches = query.all()
        if len(matches) > 1:
            return api_response(
                None,
                f'座位标签 "{label}" 匹配到多个座位，请携带 floor_id 或改用 seat_id',
                400,
            )
        seat = matches[0] if matches else None
    if not seat:
        return api_response(None, '座位不存在', 404)
    # 统一为座位数字 id：label 解析成功后，下游 SensorData / WebSocket / 返回
    # 都使用解析出的真实 seat.id（避免按 label 上报时 seat_id=None 触发 NOT NULL 错误）
    seat_id = seat.id
    # 红外已停用的座位不接收传感器上报
    if not seat.ir_enabled:
        return api_response(None, '该座位红外传感器已停用', 400)

    db.session.add(SensorData(seat_id=seat_id, ir_front=ir_front, ir_back=ir_back))
    previous_scan = seat.last_scan_time
    now = datetime.utcnow()
    seat.ir_front = ir_front
    seat.ir_back = ir_back
    seat.last_scan_time = now

    both = (ir_front == 1 and ir_back == 1)
    hours_since = (now - previous_scan).total_seconds() / 3600 if previous_scan else None

    # 先按红外更新占用状态（异常座位恢复上报时也参与状态转换）
    if both:
        if seat.status in ('free', 'error'):
            seat.status = 'occupied'
            seat.occupied_since = now
            seat.lock_available_since = now + timedelta(minutes=Config.LOCK_M_DEFAULT)
        seat.consecutive_empty = 0
    else:
        seat.consecutive_empty += 1
        if seat.consecutive_empty >= 2 and seat.status in ('occupied', 'error'):
            # 预约时段进行中：座位保持占用，不因物理无人而释放
            active_r = Reservation.query.filter(
                Reservation.seat_id == seat_id,
                Reservation.status == 'pending',
                Reservation.start_time <= now,
                Reservation.end_time > now,
            ).first()
            if active_r:
                seat.consecutive_empty = 0
            else:
                seat.status = 'free'
                seat.current_user_id = None
                seat.occupied_since = None
                seat.lock_available_since = None

    # 设备离线判定：距上次上报超过 24h → 标记异常（设备疑似故障/掉线）
    if previous_scan and hours_since > 24 and seat.status != 'error':
        seat.status = 'error'
        seat.error_since = now

    # 异常自动恢复：本次上报间隔正常（<=24h）→ 清除异常标记
    if previous_scan and hours_since <= 24 and seat.error_since:
        seat.error_since = None

    # 设备心跳：若上报携带 device_id，则刷新设备在线时间（面板“在线/离线”判定）
    dev_id = data.get('device_id')
    if dev_id:
        sdev = SensorDevice.query.filter_by(device_id=str(dev_id)).first()
        if sdev:
            sdev.last_seen = now

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


def _lock_monitor_key(record_id):
    return f'seat_lock_monitor:{record_id}'


def _lock_monitor_ttl(n):
    return max(int(n * 60) + 60, 120)


def _run_lock_monitor(record_id, seat_id, n):
    """后台监控锁定座位：连续 2 次无人后自动解锁并写入锁定记录。"""
    lock_value = None
    lock_key = _lock_monitor_key(record_id)
    if _redis_client:
        lock_value = secrets.token_hex(8)
        try:
            if not _redis_client.set(lock_key, lock_value, nx=True, ex=_lock_monitor_ttl(n)):
                return
        except Exception:
            logger.warning('Redis 锁定监控锁获取失败，继续本地监控: record=%s', record_id)
            lock_value = None

    try:
        last_check = time.monotonic()
        while True:
            time.sleep(1)
            if _redis_client and lock_value:
                try:
                    _redis_client.expire(lock_key, _lock_monitor_ttl(n))
                except Exception:
                    pass
            with app.app_context():
                seat = db.session.get(Seat, seat_id)
                record = db.session.get(LockRecord, record_id)
                if not seat or seat.status != 'locked' or not record or record.lock_end is not None:
                    return

                if seat.consecutive_empty >= 2:
                    now = datetime.utcnow()
                    record.lock_end = now
                    record.duration_sec = (now - record.lock_start).total_seconds()
                    record.detection_count += 1
                    record.auto_unlocked = True
                    seat.status = 'free'
                    seat.current_user_id = None
                    seat.occupied_since = None
                    seat.lock_available_since = None
                    db.session.commit()
                    socketio.emit('seat_update', {'seat_id': seat_id, 'status': 'free'})
                    return

                if time.monotonic() - last_check >= n * 60:
                    last_check = time.monotonic()
                    record.detection_count += 1
                    if seat.ir_front == 1 and seat.ir_back == 1:
                        record.valid_return_count += 1
                    db.session.commit()
    finally:
        if _redis_client and lock_value:
            try:
                if _redis_client.get(lock_key) == lock_value:
                    _redis_client.delete(lock_key)
            except Exception:
                logger.warning('Redis 锁定监控锁释放失败: record=%s', record_id)


def _run_lock_sweeper():
    """Redis 可用时，每个 worker 都执行清扫；分布式锁保证同一记录只有一个监控线程。"""
    while True:
        time.sleep(30)
        try:
            with app.app_context():
                records = LockRecord.query.filter_by(lock_end=None).all()
                for record in records:
                    if _redis_client and _redis_client.exists(_lock_monitor_key(record.id)):
                        continue
                    threading.Thread(
                        target=_run_lock_monitor,
                        args=(record.id, record.seat_id, Config.LOCK_N_DEFAULT),
                        daemon=True,
                    ).start()
        except Exception:
            logger.exception('锁定监控清扫任务执行失败')


_lock_sweeper_started = False


def _start_lock_sweeper():
    global _lock_sweeper_started
    if _lock_sweeper_started or not _redis_client:
        return
    _lock_sweeper_started = True
    threading.Thread(target=_run_lock_sweeper, daemon=True).start()


# ---------------------------------------------------------------------------
# 座位传感器离线扫描（主动发现掉线/故障设备）
# ---------------------------------------------------------------------------


def _run_reservation_transition():
    """预约时段状态机（每 60 秒检查一次）：
    - 预约开始时间到点 → 座位置为占用（变红，持久化到数据库）
    - 预约结束时间过期 → 座位释放为空闲（若仍有其他进行中预约则保持占用）
    """
    while True:
        time.sleep(60)
        try:
            with app.app_context():
                now = datetime.utcnow()
                changed = False

                # 到点占用：进行中的 pending 预约
                started = Reservation.query.filter(
                    Reservation.status == 'pending',
                    Reservation.start_time <= now,
                    Reservation.end_time > now,
                ).all()
                for r in started:
                    seat = db.session.get(Seat, r.seat_id)
                    if seat and seat.status == 'free':
                        seat.status = 'occupied'
                        seat.current_user_id = r.user_id
                        seat.occupied_since = now
                        seat.consecutive_empty = 0
                        changed = True
                        socketio.emit('seat_update', {
                            'seat_id': seat.id, 'status': seat.status,
                        })

                # 过期释放：已结束的 pending 预约
                expired = Reservation.query.filter(
                    Reservation.status == 'pending',
                    Reservation.end_time <= now,
                ).all()
                for r in expired:
                    seat = db.session.get(Seat, r.seat_id)
                    if not seat:
                        continue
                    still_active = Reservation.query.filter(
                        Reservation.seat_id == r.seat_id,
                        Reservation.status == 'pending',
                        Reservation.start_time <= now,
                        Reservation.end_time > now,
                        Reservation.id != r.id,
                    ).first()
                    if (not still_active and seat.status == 'occupied'
                            and seat.current_user_id == r.user_id):
                        seat.status = 'free'
                        seat.current_user_id = None
                        seat.occupied_since = None
                        seat.consecutive_empty = 0
                        changed = True
                        socketio.emit('seat_update', {
                            'seat_id': seat.id, 'status': seat.status,
                        })

                if changed:
                    db.session.commit()
        except Exception:
            logger.exception('预约时段状态机执行失败')


def _run_seat_sweeper():
    """后台主动扫描：last_scan_time 超过阈值未更新的座位标记为异常。

    与 sensor_report 的被动判定互补：传感器彻底不上报时，
    也能由本任务主动发现（无需等待新上报触发检查）。

    阈值与周期从 Config 读取（管理员可在设置页修改），
    每次循环重新读取，修改后下一轮即生效。
    """
    while True:
        # 动态读取扫描周期（分钟）
        try:
            interval_minutes = int(getattr(Config, 'SEAT_SWEEP_INTERVAL_MINUTES', 30))
            time.sleep(max(interval_minutes, 1) * 60)
        except Exception:
            time.sleep(1800)
        try:
            with app.app_context():
                offline_hours = int(getattr(Config, 'SEAT_OFFLINE_HOURS', 24))
                now = datetime.utcnow()
                cutoff = now - timedelta(hours=max(offline_hours, 1))
                # 只对「已接入传感器设备」的座位做离线判定。
                # 没有绑定任何 SensorDevice 的座位 = 尚未安装硬件，
                # 不应被当成"传感器故障"，否则后台/终端会显示一片异常，
                # 大模型也会误报成"多个座位传感器故障"。
                instrumented_ids = {
                    row[0] for row in
                    db.session.query(SensorDevice.seat_id)
                    .filter(SensorDevice.seat_id.isnot(None)).all()
                }
                changed = []
                if instrumented_ids:
                    seats = Seat.query.filter(
                        Seat.is_active == True,  # noqa: E712
                        Seat.id.in_(instrumented_ids),
                        Seat.last_scan_time.isnot(None),
                        Seat.last_scan_time < cutoff,
                    ).all()
                    for s in seats:
                        if s.status != 'error':
                            s.status = 'error'
                            s.error_since = now
                            changed.append(s.id)
                if changed:
                    db.session.commit()
                    for sid in changed:
                        socketio.emit('seat_update', {'seat_id': sid, 'status': 'error'})
                    logger.info('传感器离线扫描：%d 个座位标记为异常', len(changed))

                # ---- 掉线自动释放占用：occupied 座位超时无新上报 -> 释放为空闲 ----
                # 防止设备掉线/换绑后座位停在占用，出现"没人却一直占用"的僵尸座位。
                # 跳过预约中的座位，避免把预约中的座位误释放。
                try:
                    release_min = int(getattr(Config, 'SEAT_RELEASE_OFFLINE_MINUTES', 5))
                except Exception:
                    release_min = 5
                release_cutoff = now - timedelta(minutes=max(release_min, 1))
                stale_occupied = Seat.query.filter(
                    Seat.is_active == True,  # noqa: E712
                    Seat.status == 'occupied',
                    # 同样只针对已接入传感器的座位：无传感器的座位不会上报，
                    # 若也参与释放，会把预约/签到产生的占用状态反复清掉。
                    Seat.id.in_(instrumented_ids) if instrumented_ids else False,
                    Seat.last_scan_time.isnot(None),
                    Seat.last_scan_time < release_cutoff,
                ).all()
                released = []
                for s in stale_occupied:
                    # 跳过预约进行中的座位（预约起止时段内，物理无人也不释放）
                    active_r = Reservation.query.filter(
                        Reservation.seat_id == s.id,
                        Reservation.status == 'pending',
                        Reservation.start_time <= now,
                        Reservation.end_time > now,
                    ).first()
                    if active_r:
                        continue
                    s.status = 'free'
                    s.ir_front = 0
                    s.ir_back = 0
                    s.consecutive_empty = 0
                    s.current_user_id = None
                    s.occupied_since = None
                    s.lock_available_since = None
                    released.append(s.id)
                if released:
                    db.session.commit()
                    for sid in released:
                        socketio.emit('seat_update', {'seat_id': sid, 'status': 'free'})
                    logger.info('掉线自动释放：%d 个占用座位释放为空闲（超时 %d 分钟）',
                                len(released), release_min)
        except Exception:
            logger.exception('座位离线扫描任务执行失败')


_seat_sweeper_started = False


def _start_seat_sweeper():
    global _seat_sweeper_started
    if _seat_sweeper_started:
        return
    _seat_sweeper_started = True
    threading.Thread(target=_run_seat_sweeper, daemon=True).start()


def _ensure_ir_enabled_column():
    """轻量迁移：确保 seats 表包含 ir_enabled 列（仅 MySQL，幂等）。"""
    try:
        with app.app_context():
            if db.engine.dialect.name != 'mysql':
                return
            count = db.session.execute(text(
                "SELECT COUNT(*) FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name='seats' "
                "AND column_name='ir_enabled'"
            )).scalar()
            if not count:
                db.session.execute(text(
                    "ALTER TABLE seats ADD COLUMN ir_enabled TINYINT(1) NOT NULL DEFAULT 1"
                ))
                db.session.commit()
                logger.info('迁移：seats 表已添加 ir_enabled 列')
    except Exception as e:
        logger.warning('ir_enabled 列迁移跳过: %s', e)


@app.route('/api/lock/start', methods=['POST'])
@login_required
def start_lock():
    """启动座位锁定：连续占用满 m 分钟后可锁定，后台按 n 分钟检测无人自动解锁。"""
    data = request.get_json(silent=True) or {}
    seat_id = data.get('seat_id')
    try:
        m = float(data.get('m', Config.LOCK_M_DEFAULT))
        n = float(data.get('n', Config.LOCK_N_DEFAULT))
    except (TypeError, ValueError):
        return api_response(None, 'm/n 参数格式错误', 400)
    if not (Config.LOCK_M_RANGE[0] <= m <= Config.LOCK_M_RANGE[1]):
        return api_response(None, 'm 超出允许范围', 400)
    if not (Config.LOCK_N_RANGE[0] <= n <= Config.LOCK_N_RANGE[1]):
        return api_response(None, 'n 超出允许范围', 400)

    seat = db.session.get(Seat, seat_id)
    if not seat:
        return api_response(None, '座位不存在', 404)
    if seat.status != 'occupied':
        return api_response(None, '座位未被占用，无法锁定', 400)
    if seat.current_user_id != session['user_id'] and not _is_admin():
        return api_response(None, '无权锁定该座位', 403)
    if seat.occupied_since:
        elapsed = (datetime.utcnow() - seat.occupied_since).total_seconds() / 60
        if elapsed < m:
            return api_response(None,
                                f'需连续占用{m}分钟后方可锁定，当前已占用{elapsed:.1f}分钟', 400)

    lock_user_id = seat.current_user_id or session['user_id']
    seat.status = 'locked'
    record = LockRecord(
        user_id=lock_user_id, seat_id=seat_id,
        floor_id=seat.floor_id, lock_start=datetime.utcnow(),
    )
    db.session.add(record)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return api_response(None, '锁定失败', 500)

    threading.Thread(target=_run_lock_monitor, args=(record.id, seat_id, n), daemon=True).start()
    socketio.emit('seat_update', {'seat_id': seat_id, 'status': 'locked'})
    return api_response({
        'seat_id': seat_id, 'status': 'locked',
        'm_minutes': m, 'n_minutes': n,
    }, '锁定成功')


@app.route('/api/lock/release', methods=['POST'])
@login_required
def release_lock():
    """手动解除锁定（用户暂离后返回，结束锁定并记录时长）"""
    data = request.get_json(silent=True) or {}
    seat_id = data.get('seat_id')

    seat = db.session.get(Seat, seat_id)
    if not seat or seat.status != 'locked':
        return api_response(None, '座位未锁定', 400)

    record = LockRecord.query.filter_by(
        seat_id=seat_id, lock_end=None
    ).order_by(LockRecord.id.desc()).first()
    if not record:
        return api_response(None, '锁定记录不存在', 404)
    if record.user_id != session['user_id'] and not _is_admin():
        return api_response(None, '无权解除该锁定', 403)

    now = datetime.utcnow()
    record.lock_end = now
    record.duration_sec = (now - record.lock_start).total_seconds()
    record.auto_unlocked = False

    if data.get('keep_occupied'):
        seat.status = 'occupied'
        seat.current_user_id = seat.current_user_id or record.user_id
    else:
        seat.status = 'free'
        seat.current_user_id = None
        seat.occupied_since = None
        seat.lock_available_since = None
    db.session.commit()

    socketio.emit('seat_update', {'seat_id': seat_id, 'status': seat.status})
    return api_response({'seat_id': seat_id, 'status': seat.status}, '已解锁')


@app.route('/api/lock/status', methods=['GET'])
def lock_status():
    """查询全局锁定状态（仅用于兼容旧前端）"""
    return jsonify(seat_state)


@app.route('/api/lock/start-legacy', methods=['GET'])
def lockingo_legacy():
    """旧接口没有座位和用户上下文，无法安全启动监控，因此弃用。"""
    return api_response(None, '旧接口已废弃，请使用 /api/lock/start', 410)


# ---------------------------------------------------------------------------
# API: 最短有效回归时长机制
# ---------------------------------------------------------------------------


@app.route('/api/validate-return', methods=['POST'])
@login_required
def api_validate_return():
    """验证用户回归是否有效（防止"每 n-1 分钟回来晃一下"规避检测）"""
    data = request.get_json(silent=True) or {}
    seat_id = data.get('seat_id')
    try:
        min_duration = float(data.get('min_duration', Config.LOCK_T_DEFAULT))
    except (TypeError, ValueError):
        return api_response(None, 'min_duration 参数格式错误', 400)
    if not (Config.LOCK_T_RANGE[0] <= min_duration <= Config.LOCK_T_RANGE[1]):
        return api_response(None, 'min_duration 超出允许范围', 400)

    seat = db.session.get(Seat, seat_id)
    if not seat:
        return api_response(None, '座位不存在', 404)
    if seat.status != 'locked':
        return api_response(None, '座位当前未锁定', 400)

    record = LockRecord.query.filter_by(
        seat_id=seat_id, user_id=session['user_id'], lock_end=None
    ).first()
    if not record and not _is_admin():
        return api_response(None, '无权验证该座位', 403)

    # 这里以当前红外状态作为即时判定；真正“连续停留 min_duration 秒”的检测
    # 由锁定监控线程结合 consecutive_empty 连续计数完成。
    is_valid = bool(seat.ir_front == 1 and seat.ir_back == 1)
    tracker = get_or_create_behavior_tracker(str(session['user_id']))
    tracker.record_detection(is_valid, 0)
    tracker.record_return(is_valid)
    _save_behavior_tracker(tracker)

    return api_response({'valid': is_valid, 'min_duration': min_duration})


# ---------------------------------------------------------------------------
# API: 行为感知演进机制
# ---------------------------------------------------------------------------


@app.route('/api/behavior/report/<int:user_id>', methods=['GET'])
@login_required
def get_behavior_report(user_id):
    """获取指定用户的行为感知分析报告"""
    if user_id != session['user_id'] and not _is_admin():
        return api_response(None, '无权查看该用户报告', 403)
    tracker = get_or_create_behavior_tracker(str(user_id))
    return api_response(tracker.get_report())


@app.route('/api/admin/abnormal-users', methods=['GET'])
@admin_required
def get_abnormal_users():
    """获取行为异常（疑似恶意锁座）的用户列表"""
    abnormal = []
    user_ids = set(behavior_trackers.keys())
    if _redis_client:
        try:
            for key in _redis_client.scan_iter('behavior_tracker:*', count=100):
                user_ids.add(key.split(':', 1)[1])
        except Exception:
            logger.warning('扫描 Redis 行为数据失败，仅使用本进程数据')
    for uid in user_ids:
        tracker = get_or_create_behavior_tracker(uid)
        if tracker.is_abnormal():
            report = tracker.get_report()
            try:
                user = db.session.get(User, int(uid))
            except (TypeError, ValueError):
                user = None
            if user:
                report['user_name'] = user.name
                report['student_id'] = user.student_id
            abnormal.append(report)
    return api_response(abnormal)


# ---------------------------------------------------------------------------
# API: AI 推荐
# ---------------------------------------------------------------------------


@app.route('/api/recommend', methods=['GET'])
@login_required
def get_recommendations():
    """AI 加权推荐空闲座位（距离/区域热度/偏好匹配/拥挤度）"""
    user_id = session['user_id']
    building_id = request.args.get('building_id', type=int)
    floor_id = request.args.get('floor_id', type=int)
    user_x = request.args.get('user_x', 0, type=float)
    user_y = request.args.get('user_y', 0, type=float)
    top_k = request.args.get('top_k', 10, type=int)

    if not building_id:
        return api_response(None, '请指定建筑物', 400)

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
@login_required
def create_reservation():
    """创建座位预约（模式2：选座式，占用座位并生成二维码凭证）"""
    data = request.get_json(silent=True) or {}
    seat_id = data.get('seat_id')
    try:
        start_time = datetime.fromisoformat(data['start_time']) if data.get('start_time') else datetime.utcnow()
        end_time = datetime.fromisoformat(data['end_time']) if data.get('end_time') else start_time + timedelta(hours=2)
    except (TypeError, ValueError):
        return api_response(None, '预约时间格式不正确', 400)

    reservation, error = _create_reservation(session['user_id'], seat_id, start_time, end_time)
    if error:
        return api_response(None, error, 400)
    return api_response(reservation.to_dict(), '预约成功', 201)


@app.route('/api/reservations', methods=['GET'])
@login_required
def get_reservations():
    """获取当前用户的预约列表（管理员可指定 user_id）"""
    user_id = session['user_id']
    if _is_admin() and request.args.get('user_id', type=int):
        user_id = request.args.get('user_id', type=int)
    status = request.args.get('status')
    query = Reservation.query.filter_by(user_id=user_id)
    if status:
        query = query.filter_by(status=status)
    reservations = query.order_by(Reservation.created_at.desc()).all()
    return api_response([r.to_dict() for r in reservations])


def _make_qrcode_png(data: str):
    """生成包含指定内容的二维码 PNG，返回 BytesIO。"""
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=8, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


def _do_checkin(reservation):
    """公共签到逻辑：pending → checked_in，并广播座位占用状态。"""
    reservation.status = 'checked_in'
    reservation.checkin_time = datetime.utcnow()
    db.session.commit()
    socketio.emit('seat_update', {'seat_id': reservation.seat_id, 'status': 'occupied'})
    return api_response(reservation.to_dict(), '签到成功')


@app.route('/api/reservations/<int:reservation_id>/checkin', methods=['POST'])
@login_required
def checkin_reservation(reservation_id):
    """按钮签到：pending → checked_in。

    仅当「传感器检测到座位有人」且「用户定位在座位附近」时才允许，
    否则返回具体失败原因（用于前端提示"无法签到"）。
    """
    reservation = Reservation.query.get_or_404(reservation_id)
    if reservation.user_id != session['user_id'] and not _is_admin():
        return api_response(None, '无权操作该预约', 403)
    if reservation.status != 'pending':
        return api_response(None, '预约状态无效', 400)

    seat = db.session.get(Seat, reservation.seat_id)
    if not seat:
        return api_response(None, '座位不存在', 404)

    # 条件1：传感器检测到座位上有人（红外双光束同时遮挡）
    if not (seat.ir_front == 1 and seat.ir_back == 1):
        return api_response(None, '无法签到：座位传感器未检测到有人，请入座后重试', 400)

    # 条件2：本人在座位附近（用户定位节点 == 座位最近路网节点）
    data = request.get_json(silent=True) or {}
    loc_node_id = (data.get('loc_node_id') or '').strip() or None
    if seat.nearest_node_id:
        if not loc_node_id:
            return api_response(None, '无法签到：请先在导航页扫码定位到座位附近', 400)
        if loc_node_id != seat.nearest_node_id:
            return api_response(None, '无法签到：您不在该座位附近', 400)

    return _do_checkin(reservation)


@app.route('/api/checkin/scan', methods=['POST'])
@login_required
def checkin_scan():
    """扫码签到：支持 座位码(SEAT:<id>) 与 预约二维码Token 两种内容。

    受 Config.CHECKIN_QR_ENABLED 开关控制，未开启时返回 400。
    """
    if not Config.CHECKIN_QR_ENABLED:
        return api_response(None, '二维码签到功能未开启，请联系管理员', 400)

    data = request.get_json(silent=True) or {}
    token = (data.get('token') or '').strip()
    if not token:
        return api_response(None, '请提供二维码内容', 400)

    reservation = None
    if token.startswith('SEAT:'):
        # 座位码：扫桌面上粘贴的座位二维码
        try:
            seat_id = int(token.split(':', 1)[1])
        except (ValueError, IndexError):
            return api_response(None, '二维码无效', 400)
        seat = db.session.get(Seat, seat_id)
        if not seat:
            return api_response(None, '座位不存在', 404)
        reservation = Reservation.query.filter_by(
            seat_id=seat_id, user_id=session['user_id'], status='pending'
        ).order_by(Reservation.created_at.desc()).first()
        if not reservation:
            return api_response(None, '该座位没有您的待签到预约', 404)
    else:
        # 预约码：扫码枪/设备读取预约二维码内容
        reservation = Reservation.query.filter_by(qr_token=token).first()
        if not reservation:
            return api_response(None, '二维码无效或已失效', 404)
        if reservation.user_id != session['user_id'] and not _is_admin():
            return api_response(None, '无权操作该预约', 403)

    if reservation.status != 'pending':
        return api_response(None, '预约状态无效', 400)
    return _do_checkin(reservation)


@app.route('/api/seats/<int:seat_id>/qrcode')
@admin_required
def seat_qrcode(seat_id):
    """座位二维码（管理员打印后粘贴到桌子上，内容为 SEAT:<id>）。"""
    seat = db.session.get(Seat, seat_id)
    if not seat:
        return api_response(None, '座位不存在', 404)
    return send_file(_make_qrcode_png(f'SEAT:{seat.id}'), mimetype='image/png')


@app.route('/api/reservations/<int:reservation_id>/qrcode')
@login_required
def reservation_qrcode(reservation_id):
    """预约二维码（本人查看，内容为预约 qr_token，受开关控制）。"""
    if not Config.CHECKIN_QR_ENABLED:
        return api_response(None, '二维码签到功能未开启，请联系管理员', 403)
    reservation = Reservation.query.get_or_404(reservation_id)
    if reservation.user_id != session['user_id'] and not _is_admin():
        return api_response(None, '无权查看该二维码', 403)
    return send_file(_make_qrcode_png(reservation.qr_token), mimetype='image/png')


@app.route('/api/reservations/<int:reservation_id>/cancel', methods=['POST'])
@login_required
def cancel_reservation(reservation_id):
    """取消预约并释放座位，仅本人或管理员可操作"""
    reservation = Reservation.query.get_or_404(reservation_id)
    if reservation.user_id != session['user_id'] and not _is_admin():
        return api_response(None, '无权操作该预约', 403)
    if reservation.status in ['completed', 'cancelled']:
        return api_response(None, '预约已结束', 400)
    reservation.status = 'cancelled'
    seat = db.session.get(Seat, reservation.seat_id)
    if seat and (seat.current_user_id == reservation.user_id or _is_admin()):
        seat.status = 'free'
        seat.current_user_id = None
        seat.occupied_since = None
        seat.lock_available_since = None
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
        stair_nodes = _get_stair_nodes(from_floor_id, to_floor_id)
        result = navigation_service.plan_cross_floor(
            from_floor_id, to_floor_id, from_node, to_node, stair_nodes)
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
@admin_required
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


@app.route('/api/admin/network/<int:floor_id>', methods=['DELETE'])
@admin_required
def delete_network(floor_id):
    """删除指定楼层已生成/保存的路网数据（文件 + 数据库引用 + 内存缓存）"""
    floor = Floor.query.get_or_404(floor_id)
    old_path = floor.road_network_path
    floor.road_network_path = None
    db.session.commit()

    # 删除路网文件
    if old_path and os.path.exists(old_path):
        try:
            os.remove(old_path)
            logger.info('已删除路网文件: %s', old_path)
        except OSError as e:
            logger.warning('删除路网文件失败: %s', e)
    # 清除导航内存缓存
    navigation_service.networks.pop(floor_id, None)
    # 删除路网预览图
    preview = os.path.join(app.root_path, 'data', 'overlays', f'floor_{floor_id}_preview.jpg')
    if os.path.exists(preview):
        try:
            os.remove(preview)
        except OSError:
            pass
    return api_response(None, '路网已删除')


# ---------------------------------------------------------------------------
# API: 平面图上传
# ---------------------------------------------------------------------------


@app.route('/api/upload', methods=['POST'])
@admin_required
def upload_floor_plan():
    """上传平面图：保存文件并返回图片尺寸信息"""
    if 'file' not in request.files:
        return api_response(None, '请选择文件', 400)
    file = request.files['file']
    if file.filename == '':
        return api_response(None, '文件名为空', 400)

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ('.png', '.jpg', '.jpeg', '.webp', '.bmp'):
        return api_response(None, '仅支持 PNG/JPG/WEBP/BMP 图片', 400)

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


# ---------------------------------------------------------------------------
# API: 自动建图（view/auto_mapping 接入主函数）
# ---------------------------------------------------------------------------


@app.route('/outputs/<path:filename>')
def view_output_file(filename):
    """提供自动建图输出（拼接图 stitched.jpg / plane.json / 关键帧）的静态访问"""
    return send_from_directory(VIEW_OUTPUTS_DIR, filename)


def _cleanup_old_mapping_tasks(keep_task_id):
    """只保留最后一次成功的建图结果：删除其它运行时 room_* 任务目录。

    已提交的示例目录（opt_test/test_room/test_room2/video_test）不受影响。
    """
    try:
        for name in os.listdir(VIEW_OUTPUTS_DIR):
            if name.startswith('room_') and name != keep_task_id:
                shutil.rmtree(os.path.join(VIEW_OUTPUTS_DIR, name), ignore_errors=True)
    except OSError as e:
        logger.warning('清理旧建图任务失败: %s', e)


@app.route('/api/admin/mapping/tasks', methods=['POST'])
@admin_required
def create_mapping_task():
    """创建自动建图任务。

    上传方式（multipart/form-data）：
      - file: 单个视频文件（mp4/mov/avi/mkv/webm/m4v），调用 process_video
      - file: 多张图片（重复字段名），调用 process_frames
    可选表单字段：
      - name        房间名称，默认「自动建模房间」
      - line_method 直线检测方式 lsd / hough，默认 lsd
      - mode        强制指定 video / images

    注意：v1 为同步执行（处理期间请求会等待），耗时取决于素材；
    后续如需异步可升级为后台线程 + 任务状态查询。
    """
    if not _AUTO_MAPPING_AVAILABLE:
        return api_response(None, '自动建图模块不可用（请检查 view 模块及 opencv/numpy 依赖）', 500)

    files = request.files.getlist('file')
    files = [f for f in files if f and f.filename]
    temp_files = []
    try:
        if not files:
            return api_response(None, '请上传视频或图片', 400)

        name = request.form.get('name') or '自动建模房间'
        line_method = request.form.get('line_method', 'lsd')
        if line_method not in ('lsd', 'hough'):
            line_method = 'lsd'
        task_id = 'room_' + uuid.uuid4().hex[:8]

        first_filename = files[0].filename or ''
        ext = os.path.splitext(first_filename)[1].lower()
        video_exts = ('.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v')
        mode = request.form.get('mode')
        is_video = (mode == 'video') or (mode != 'images' and ext in video_exts)

        if is_video:
            if len(files) > 1:
                return api_response(None, '视频模式一次只允许上传一个文件', 400)
            video_path = os.path.join(Config.UPLOAD_FOLDER, f'{task_id}.mp4')
            files[0].save(video_path)
            temp_files.append(video_path)
            result = _map_process_video(
                video_path,
                output_dir=VIEW_OUTPUTS_DIR,
                task_id=task_id,
                name=name,
                line_method=line_method,
            )
        else:
            frame_dir = os.path.join(VIEW_OUTPUTS_DIR, task_id, 'frames')
            os.makedirs(frame_dir, exist_ok=True)
            for i, f in enumerate(files):
                save_path = os.path.join(frame_dir, f'{i:03d}_{secure_filename(f.filename)}')
                f.save(save_path)
                temp_files.append(save_path)
            result = _map_process_frames(
                frame_dir,
                output_dir=VIEW_OUTPUTS_DIR,
                task_id=task_id,
                name=name,
                line_method=line_method,
            )

        if not result:
            return api_response(
                None,
                '自动建图失败：素材不适合拼接（帧间匹配率过低）。'
                '请改用俯视/平移拍摄（画面有纹理、帧间重叠≥50%），'
                '或直接使用「手动上传」CAD 导出的平面图',
                400,
            )

        # 成功后才覆盖：删除旧的运行时任务，只保留本次成功结果
        _cleanup_old_mapping_tasks(result['room']['id'])

        return api_response({
            'task_id': result['room']['id'],
            'room': result['room'],
            'image': result['image'],
            'lines': result['lines'],
            'unit': result['unit'],
            'line_count': len(result['lines']),
        }, '自动建图成功')

    except Exception as e:
        logger.exception('自动建图异常')
        return api_response(None, f'自动建图失败：{e}', 500)
    finally:
        for p in temp_files:
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass


@app.route('/api/admin/mapping/tasks/<task_id>', methods=['GET'])
@admin_required
def get_mapping_task(task_id):
    """查询自动建图任务结果（用于页面刷新后恢复状态）"""
    plane_path = os.path.join(VIEW_OUTPUTS_DIR, task_id, 'plane.json')
    if not os.path.exists(plane_path):
        return api_response(None, '任务不存在或已清理', 404)
    try:
        with open(plane_path, 'r', encoding='utf-8') as f:
            plane = json.load(f)
    except (OSError, ValueError) as e:
        return api_response(None, f'任务结果读取失败：{e}', 500)
    return api_response({
        'task_id': task_id,
        'status': 'done',
        'room': plane.get('room'),
        'image': plane.get('image'),
        'lines': plane.get('lines', []),
        'unit': plane.get('unit'),
    })


@app.route('/api/admin/mapping/tasks/<task_id>/apply', methods=['POST'])
@admin_required
def apply_mapping_task(task_id):
    """把自动建图结果应用到指定楼层。

    将拼接图复制到 uploads 目录（复用现有 /uploads 访问与 to_dict 的 floor_plan_url 逻辑），
    并更新楼层平面图路径/宽高，之后即可在「平面图与路网配置」页继续添加座位、生成路网。
    """
    data = request.get_json(silent=True) or {}
    floor_id = data.get('floor_id')
    if not floor_id:
        return api_response(None, '缺少 floor_id', 400)
    floor = db.session.get(Floor, floor_id)
    if not floor:
        return api_response(None, '楼层不存在', 404)

    plane_path = os.path.join(VIEW_OUTPUTS_DIR, task_id, 'plane.json')
    stitched_path = os.path.join(VIEW_OUTPUTS_DIR, task_id, 'stitched.jpg')
    if not os.path.exists(plane_path) or not os.path.exists(stitched_path):
        return api_response(None, '建图结果不存在', 404)

    try:
        with open(plane_path, 'r', encoding='utf-8') as f:
            plane = json.load(f)
    except (OSError, ValueError) as e:
        return api_response(None, f'建图结果读取失败：{e}', 500)

    dest_path = os.path.join(Config.UPLOAD_FOLDER, f'plane_{task_id}.jpg')
    shutil.copyfile(stitched_path, dest_path)

    floor.floor_plan_path = dest_path
    floor.floor_plan_width = (plane.get('image') or {}).get('width')
    floor.floor_plan_height = (plane.get('image') or {}).get('height')
    db.session.commit()

    return api_response({
        'floor_id': floor.id,
        'floor_plan_url': f'/uploads/{os.path.basename(dest_path)}',
        'width': floor.floor_plan_width,
        'height': floor.floor_plan_height,
    }, '建图结果已应用')


@app.route('/data/<path:filename>')
def data_file(filename):
    """提供 data 目录（路网JSON/叠加预览图等）的静态访问"""
    return send_from_directory(os.path.join(app.root_path, 'data'), filename)


# ---------------------------------------------------------------------------
# API: 系统配置
# ---------------------------------------------------------------------------


def _apply_runtime_config(data):
    """校验并应用运行期配置，同时持久化到 data/system_config.json。"""
    updates = {}
    try:
        if 'lock_m_default' in data:
            value = int(data['lock_m_default'])
            if not (Config.LOCK_M_RANGE[0] <= value <= Config.LOCK_M_RANGE[1]):
                return {}, 'lock_m_default 超出允许范围'
            updates['lock_m_default'] = value
        if 'lock_n_default' in data:
            value = int(data['lock_n_default'])
            if not (Config.LOCK_N_RANGE[0] <= value <= Config.LOCK_N_RANGE[1]):
                return {}, 'lock_n_default 超出允许范围'
            updates['lock_n_default'] = value
        if 'lock_t_default' in data:
            value = int(data['lock_t_default'])
            if not (Config.LOCK_T_RANGE[0] <= value <= Config.LOCK_T_RANGE[1]):
                return {}, 'lock_t_default 超出允许范围'
            updates['lock_t_default'] = value
        if 'ai_weights' in data:
            value = list(data['ai_weights'])
            if len(value) != 4 or abs(sum(value) - 1.0) > 0.01:
                return {}, 'ai_weights 必须为 4 个且和为 1'
            updates['ai_weights'] = value
        if 'sensor_scan_interval' in data:
            value = int(data['sensor_scan_interval'])
            if value <= 0:
                return {}, 'sensor_scan_interval 必须大于 0'
            updates['sensor_scan_interval'] = value
        if 'checkin_qr_enabled' in data:
            updates['checkin_qr_enabled'] = bool(data['checkin_qr_enabled'])
        if 'seat_offline_hours' in data:
            value = int(data['seat_offline_hours'])
            if not (1 <= value <= 720):
                return {}, 'seat_offline_hours 超出范围（1~720小时）'
            updates['seat_offline_hours'] = value
        if 'seat_sweep_interval_minutes' in data:
            value = int(data['seat_sweep_interval_minutes'])
            if not (1 <= value <= 1440):
                return {}, 'seat_sweep_interval_minutes 超出范围（1~1440分钟）'
            updates['seat_sweep_interval_minutes'] = value
        if 'seat_online_timeout_minutes' in data:
            value = int(data['seat_online_timeout_minutes'])
            if not (1 <= value <= 120):
                return {}, 'seat_online_timeout_minutes 超出范围（1~120分钟）'
            updates['seat_online_timeout_minutes'] = value
        # ---- 室外导航地图配置 ----
        if 'nav_map_provider' in data:
            provider = str(data['nav_map_provider']).strip().lower()
            if provider not in ('amap', 'baidu', 'none'):
                return {}, 'nav_map_provider 必须为 amap / baidu / none'
            updates['nav_map_provider'] = provider
        if 'nav_map_key' in data:
            # 留空 = 不修改；__CLEAR__ = 显式清除
            key = str(data['nav_map_key']).strip()
            if key == '__CLEAR__':
                updates['nav_map_key'] = ''
            elif key:
                updates['nav_map_key'] = key
        if 'nav_map_security_code' in data:
            code = str(data['nav_map_security_code']).strip()
            if code == '__CLEAR__':
                updates['nav_map_security_code'] = ''
            elif code:
                updates['nav_map_security_code'] = code
        if 'nav_fallback_enabled' in data:
            updates['nav_fallback_enabled'] = bool(data['nav_fallback_enabled'])

        # ---- 大模型 AI 配置（支持在管理后台切换在线 API 供应商） ----
        if 'ai_enabled' in data:
            updates['ai_enabled'] = bool(data['ai_enabled'])
        if 'ai_provider' in data:
            provider = str(data['ai_provider']).strip().lower()
            presets = getattr(Config, 'AI_PROVIDER_PRESETS', {})
            if provider not in presets and provider != 'custom':
                return {}, f'ai_provider 无效（可选：{"/".join(list(presets) + ["custom"])}）'
            updates['ai_provider'] = provider
            # 切换供应商时，未显式给出地址/模型 -> 自动套用该供应商预设
            if provider in presets:
                if not str(data.get('ai_base_url', '')).strip():
                    updates['ai_base_url'] = presets[provider]['base_url']
                if not str(data.get('ai_model', '')).strip():
                    updates['ai_model'] = presets[provider]['model']
        if 'ai_base_url' in data:
            base_url = str(data['ai_base_url']).strip()
            if base_url and not base_url.startswith(('http://', 'https://')):
                return {}, 'ai_base_url 必须以 http:// 或 https:// 开头'
            if base_url:
                updates['ai_base_url'] = base_url.rstrip('/')
        if 'ai_model' in data:
            model = str(data['ai_model']).strip()
            if model:
                updates['ai_model'] = model
        if 'ai_api_key' in data:
            # 允许留空表示"不修改"；传入 __CLEAR__ 显式清除
            key = str(data['ai_api_key']).strip()
            if key == '__CLEAR__':
                updates['ai_api_key'] = ''
            elif key:
                updates['ai_api_key'] = key
        if 'ai_timeout' in data:
            value = int(data['ai_timeout'])
            if not (3 <= value <= 120):
                return {}, 'ai_timeout 超出范围（3~120秒）'
            updates['ai_timeout'] = value
        if 'ai_max_tokens' in data:
            value = int(data['ai_max_tokens'])
            if not (50 <= value <= 4000):
                return {}, 'ai_max_tokens 超出范围（50~4000）'
            updates['ai_max_tokens'] = value
        if 'ai_temperature' in data:
            value = float(data['ai_temperature'])
            if not (0.0 <= value <= 2.0):
                return {}, 'ai_temperature 超出范围（0~2）'
            updates['ai_temperature'] = value
        if 'ai_cache_ttl' in data:
            value = int(data['ai_cache_ttl'])
            if not (0 <= value <= 3600):
                return {}, 'ai_cache_ttl 超出范围（0~3600秒）'
            updates['ai_cache_ttl'] = value

        # ---- 智能终端显示位置 ----
        if 'terminal_building_id' in data:
            try:
                value = int(data['terminal_building_id'] or 0)
            except (TypeError, ValueError):
                return {}, 'terminal_building_id 必须为数字'
            updates['terminal_building_id'] = max(0, value)
        if 'terminal_floor_id' in data:
            try:
                value = int(data['terminal_floor_id'] or 0)
            except (TypeError, ValueError):
                return {}, 'terminal_floor_id 必须为数字'
            updates['terminal_floor_id'] = max(0, value)
        if 'terminal_title' in data:
            updates['terminal_title'] = str(data['terminal_title']).strip()[:60]
    except (TypeError, ValueError):
        return {}, '配置值格式错误'

    if not updates:
        return {}, '没有可更新的配置项'

    for key, value in updates.items():
        setattr(Config, key.upper(), value)
    if 'ai_weights' in updates:
        recommendation_engine.update_weights(Config.AI_WEIGHTS)
    if 'sensor_scan_interval' in updates:
        sensor_simulator.scan_interval = Config.SENSOR_SCAN_INTERVAL
    # AI 配置变更 -> 重建 LLM 客户端与服务，立即生效（无需重启）
    if any(k.startswith('ai_') and k not in ('ai_weights',) for k in updates):
        reload_llm()
        reset_ai_services()

    # 合并写入：先读旧配置再覆盖，避免保存单项时清掉其它配置
    os.makedirs(os.path.dirname(_RUNTIME_CONFIG_FILE), exist_ok=True)
    existing = {}
    if os.path.exists(_RUNTIME_CONFIG_FILE):
        try:
            with open(_RUNTIME_CONFIG_FILE, 'r', encoding='utf-8') as f:
                existing = json.load(f) or {}
        except (OSError, ValueError):
            existing = {}
    existing.update(updates)
    with open(_RUNTIME_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    return updates, None


@app.route('/api/admin/config', methods=['GET', 'PUT'])
@admin_required
def system_config():
    """查看 / 更新系统配置（锁定参数、AI权重、传感器间隔等）"""
    if request.method == 'GET':
        ai_key = getattr(Config, 'AI_API_KEY', '') or ''
        presets = {}
        for name, preset in (getattr(Config, 'AI_PROVIDER_PRESETS', {}) or {}).items():
            presets[name] = {'base_url': preset.get('base_url'), 'model': preset.get('model')}
        return api_response({
            'lock_m_default': Config.LOCK_M_DEFAULT,
            'lock_n_default': Config.LOCK_N_DEFAULT,
            'lock_t_default': Config.LOCK_T_DEFAULT,
            'lock_m_range': Config.LOCK_M_RANGE,
            'lock_n_range': Config.LOCK_N_RANGE,
            'lock_t_range': Config.LOCK_T_RANGE,
            'ai_weights': Config.AI_WEIGHTS,
            'sensor_scan_interval': Config.SENSOR_SCAN_INTERVAL,
            'checkin_qr_enabled': Config.CHECKIN_QR_ENABLED,
            'seat_offline_hours': Config.SEAT_OFFLINE_HOURS,
            'seat_sweep_interval_minutes': Config.SEAT_SWEEP_INTERVAL_MINUTES,
            'seat_release_offline_minutes': getattr(Config, 'SEAT_RELEASE_OFFLINE_MINUTES', 5),
            'seat_online_timeout_minutes': getattr(Config, 'SEAT_ONLINE_TIMEOUT_MINUTES', 3),
            # ---- 室外导航地图（key 只回传掩码，绝不回传明文）----
            'nav_map_provider': getattr(Config, 'NAV_MAP_PROVIDER', 'amap'),
            'nav_map_key_set': bool(getattr(Config, 'NAV_MAP_KEY', '')),
            'nav_map_key_masked': _mask_secret(getattr(Config, 'NAV_MAP_KEY', '')),
            'nav_map_security_set': bool(getattr(Config, 'NAV_MAP_SECURITY_CODE', '')),
            'nav_fallback_enabled': getattr(Config, 'NAV_FALLBACK_ENABLED', True),
            # ---- 大模型 AI（密钥只回传"是否已设置"，绝不回传明文）----
            'ai_enabled': getattr(Config, 'AI_ENABLED', True),
            'ai_provider': getattr(Config, 'AI_PROVIDER', 'deepseek'),
            'ai_base_url': getattr(Config, 'AI_BASE_URL', ''),
            'ai_model': getattr(Config, 'AI_MODEL', ''),
            'ai_api_key_set': bool(ai_key),
            'ai_api_key_masked': (ai_key[:6] + '****' + ai_key[-4:]) if len(ai_key) > 12 else ('****' if ai_key else ''),
            'ai_timeout': getattr(Config, 'AI_TIMEOUT', 20),
            'ai_max_tokens': getattr(Config, 'AI_MAX_TOKENS', 600),
            'ai_temperature': getattr(Config, 'AI_TEMPERATURE', 0.3),
            'ai_cache_ttl': getattr(Config, 'AI_CACHE_TTL', 60),
            'ai_provider_presets': presets,
            # ---- 智能终端显示位置 ----
            'terminal_building_id': getattr(Config, 'TERMINAL_BUILDING_ID', 0),
            'terminal_floor_id': getattr(Config, 'TERMINAL_FLOOR_ID', 0),
            'terminal_title': getattr(Config, 'TERMINAL_TITLE', '智能座位导引'),
            'buildings': [
                {'id': b.id, 'name': b.name}
                for b in Building.query.filter_by(is_active=True).order_by(Building.id).all()
            ],
            'floors': [
                {'id': f.id, 'name': (f.name or f'{f.floor_number}F'),
                 'building_id': f.building_id}
                for f in Floor.query.filter(Floor.is_active == True)  # noqa: E712
                                 .order_by(Floor.building_id, Floor.floor_number).all()
            ],
        })
    data = request.get_json(silent=True) or {}
    updates, error = _apply_runtime_config(data)
    if error:
        return api_response(None, error, 400)
    return api_response(None, '配置已更新')


# ---------------------------------------------------------------------------
# API: 传感器模拟器控制
# ---------------------------------------------------------------------------


def _build_sensor_simulator(interval=None):
    """创建传感器模拟器并装配数据回调（不启动）。

    回调逻辑与真实传感器上报（/api/sensor/report）保持一致：
    异常座位在收到上报后自动恢复（有人→占用；连续2次无人→空闲）。
    """
    global sensor_simulator
    interval = interval or Config.SENSOR_SCAN_INTERVAL
    seat_ids = [row[0] for row in db.session.query(Seat.id).filter_by(is_active=True).all()]

    sim = SensorSimulator(seat_ids=seat_ids, scan_interval=interval)

    def sensor_callback(seat_id, ir_front, ir_back):
        """模拟器回调：把红外数据写入座位并更新状态，通过 WebSocket 推送前端"""
        with app.app_context():
            seat = Seat.query.get(seat_id)
            # 红外已停用的座位跳过（管理员主动关闭）
            if seat and not seat.ir_enabled:
                return
            if seat:
                now = datetime.utcnow()
                seat.ir_front = ir_front
                seat.ir_back = ir_back
                seat.last_scan_time = now
                both = ir_front == 1 and ir_back == 1
                if both:
                    # 异常座位收到"有人"上报时同样恢复为占用
                    if seat.status in ('free', 'error'):
                        seat.status = 'occupied'
                        seat.occupied_since = now
                        seat.lock_available_since = now + timedelta(minutes=Config.LOCK_M_DEFAULT)
                    seat.consecutive_empty = 0
                else:
                    seat.consecutive_empty += 1
                    if seat.consecutive_empty >= 2 and seat.status in ('occupied', 'error'):
                        # 预约时段进行中：座位保持占用，不因物理无人而释放
                        active_r = Reservation.query.filter(
                            Reservation.seat_id == seat_id,
                            Reservation.status == 'pending',
                            Reservation.start_time <= now,
                            Reservation.end_time > now,
                        ).first()
                        if active_r:
                            seat.consecutive_empty = 0
                        else:
                            seat.status = 'free'
                            seat.current_user_id = None
                            seat.occupied_since = None
                            seat.lock_available_since = None
                # 离开异常状态后清除异常标记
                if seat.status != 'error' and seat.error_since:
                    seat.error_since = None
                db.session.commit()
                socketio.emit('seat_update', {
                    'seat_id': seat_id, 'status': seat.status,
                    'ir_front': ir_front, 'ir_back': ir_back,
                })

    sim.set_callback(sensor_callback)
    return sim


def _autostart_sensor_simulator():
    """应用启动时按配置自动启动传感器模拟器，避免座位因无上报被标记异常。"""
    global sensor_simulator
    if not getattr(Config, 'SENSOR_SIMULATOR_AUTOSTART', False):
        return
    if sensor_simulator.running:
        return
    try:
        with app.app_context():
            sensor_simulator = _build_sensor_simulator()
            sensor_simulator.start()
            logger.info('传感器模拟器已自动启动（SENSOR_SIMULATOR_AUTOSTART=True，间隔 %ds）',
                        Config.SENSOR_SCAN_INTERVAL)
    except Exception as e:
        logger.warning('传感器模拟器自动启动失败: %s', e)


@app.route('/api/admin/simulator/start', methods=['POST'])
@admin_required
def start_simulator():
    """启动传感器模拟器（后台线程随机上报红外数据）"""
    data = request.get_json(silent=True) or {}
    try:
        interval = int(data.get('interval', Config.SENSOR_SCAN_INTERVAL))
    except (TypeError, ValueError):
        return api_response(None, 'interval 参数格式错误', 400)
    if interval <= 0:
        return api_response(None, 'interval 必须大于 0', 400)

    global sensor_simulator
    if sensor_simulator.running:
        sensor_simulator.stop()
    sensor_simulator = _build_sensor_simulator(interval)
    sensor_simulator.start()
    return api_response({'seat_count': sensor_simulator.seat_count, 'interval': interval}, '模拟器已启动')


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
    data = request.get_json(silent=True) or {}
    seat_id = data.get('seat_id')
    occupied = data.get('occupied', True)
    if not sensor_simulator.simulate_occupancy(seat_id, occupied):
        return api_response(None, '模拟器未覆盖该座位，请先启动模拟器', 400)
    return api_response(None, f'座位{seat_id} {"占用" if occupied else "释放"}模拟已触发')


@app.route('/api/admin/sensor/overview', methods=['GET'])
@admin_required
def sensor_overview():
    """硬件/传感器调试面板数据：全局参数 + 模拟器状态 + 每座位传感器实时状态。"""
    # 「在线」与「座位异常」是两种语义，必须用不同阈值：
    #   * 在线/离线：设备正常每 1 秒上报一次，几分钟没动静就该判离线
    #     （此前误用 SEAT_OFFLINE_HOURS=1 小时，导致断电后仍显示「在线」达一小时）
    #   * 座位异常：长时间失联才标记 error，用 SEAT_OFFLINE_HOURS
    online_timeout_min = int(getattr(Config, 'SEAT_ONLINE_TIMEOUT_MINUTES', 3))
    now = datetime.utcnow()
    seats = []
    for s in db.session.query(Seat).filter_by(is_active=True).all():
        last_ts = s.last_scan_time
        age_sec = (now - last_ts).total_seconds() if last_ts else None
        online = bool(age_sec is not None and age_sec <= online_timeout_min * 60)
        seats.append({
            'id': s.id,
            'seat_label': s.seat_label,
            'floor_name': s.floor.name if s.floor else '',
            'building_name': s.floor.building.name if (s.floor and s.floor.building) else '',
            'status': s.status,
            'ir_front': s.ir_front,
            'ir_back': s.ir_back,
            'ir_enabled': s.ir_enabled,
            'is_active': s.is_active,
            'online': online,
            'last_scan_age_sec': int(age_sec) if age_sec is not None else None,
            'last_scan_time': last_ts.isoformat() if last_ts else None,
        })
    return api_response({
        'config': {
            'sensor_scan_interval': Config.SENSOR_SCAN_INTERVAL,
            'seat_offline_hours': int(getattr(Config, 'SEAT_OFFLINE_HOURS', 24)),
        'seat_online_timeout_minutes': online_timeout_min,
            'seat_sweep_interval_minutes': Config.SEAT_SWEEP_INTERVAL_MINUTES,
        },
        'simulator_running': bool(getattr(sensor_simulator, 'running', False)),
        'seats': seats,
    })


# ---------------------------------------------------------------------------
# API: 传感器设备注册 / 配置下发（ESP32 首次联网自动注册；改配置免重烧）
# ---------------------------------------------------------------------------


def _device_config_payload(dev):
    """把设备及其绑定座位构造成设备端需要的配置。"""
    seat = dev.seat if dev.seat_id else None
    return {
        'device_id': dev.device_id,
        'registered': True,
        'ir_active_high': bool(dev.ir_active_high),
        'sensor_type': getattr(dev, 'sensor_type', 'pir') or 'pir',
        'distance_threshold_cm': int(getattr(dev, 'distance_threshold_cm', 50) or 50),
        'report_interval_ms': int(dev.report_interval_ms or 5000),
        'seat_id': seat.id if seat else None,
        'seat_label': seat.seat_label if seat else None,
        'floor_id': seat.floor_id if seat else None,
    }


@app.route('/api/sensor/device/register', methods=['POST'])
def sensor_device_register():
    """设备开机注册/心跳：新设备自动登记（面板可提示“已注册成功”），返回下发配置。"""
    data = request.get_json(silent=True) or {}
    device_id = str(data.get('device_id', '')).strip()
    if not device_id:
        return api_response(None, '缺少 device_id', 400)
    dev = SensorDevice.query.filter_by(device_id=device_id).first()
    is_new = dev is None
    if dev is None:
        dev = SensorDevice(device_id=device_id, is_new=True)
        db.session.add(dev)
    dev.last_seen = datetime.utcnow()
    if is_new:
        dev.is_new = True
    db.session.commit()
    return api_response({
        'registered': True,
        'is_new': is_new,
        'config': _device_config_payload(dev),
    }, '设备注册成功')


@app.route('/api/sensor/device_config', methods=['GET'])
def sensor_device_config():
    """设备拉取当前配置。管理员在面板改完配置后，设备周期拉取即生效（免重烧）。"""
    device_id = request.args.get('device_id', '').strip()
    if not device_id:
        return api_response(None, '缺少 device_id', 400)
    dev = SensorDevice.query.filter_by(device_id=device_id).first()
    if dev is None:
        return api_response({'registered': False, 'device_id': device_id, 'config': None}, '设备未注册，请先注册')
    dev.last_seen = datetime.utcnow()
    db.session.commit()
    return api_response({'registered': True, 'device_id': device_id, 'config': _device_config_payload(dev)})


@app.route('/api/admin/sensor/devices', methods=['GET'])
@admin_required
def admin_sensor_devices():
    """设备管理列表：每台设备（MAC/在线/绑定座位/配置）+ 新设备标记。"""
    # 同 sensor_overview：在线判定用短超时，避免断电后仍长时间显示「在线」
    online_timeout_min = int(getattr(Config, 'SEAT_ONLINE_TIMEOUT_MINUTES', 3))
    now = datetime.utcnow()
    rows = []
    for d in SensorDevice.query.order_by(SensorDevice.last_seen.desc()).all():
        r = d.to_dict()
        age_sec = (now - d.last_seen).total_seconds() if d.last_seen else None
        r['online'] = bool(age_sec is not None and age_sec <= online_timeout_min * 60)
        r['last_seen_age_sec'] = int(age_sec) if age_sec is not None else None
        rows.append(r)
    return api_response({'devices': rows,
                         'online_timeout_minutes': online_timeout_min})


@app.route('/api/admin/sensor/devices/<int:device_pk>', methods=['PUT'])
@admin_required
def admin_sensor_device_update(device_pk):
    """绑定座位 / 选传感器类型 / 设上报间隔；保存后视为“已处理”，清除新设备标记。"""
    dev = db.session.get(SensorDevice, device_pk)
    if not dev:
        return api_response(None, '设备不存在', 404)
    data = request.get_json(silent=True) or {}
    if 'seat_id' in data:
        seat_id = data.get('seat_id')
        if seat_id is not None and str(seat_id).strip() != '':
            try:
                seat_id = int(seat_id)
            except (TypeError, ValueError):
                return api_response(None, 'seat_id 必须为数字', 400)
            seat = db.session.get(Seat, seat_id)
            if not seat:
                return api_response(None, '座位不存在', 400)
            dev.seat_id = seat.id
        else:
            dev.seat_id = None
    if 'ir_active_high' in data:
        dev.ir_active_high = bool(data['ir_active_high'])
    if 'sensor_type' in data:
        st = str(data['sensor_type']).strip()
        if st not in ('pir', 'ir', 'ultrasonic'):
            return api_response(None, 'sensor_type 必须为 pir/ir/ultrasonic', 400)
        dev.sensor_type = st
    if 'distance_threshold_cm' in data:
        try:
            dev.distance_threshold_cm = max(5, int(data['distance_threshold_cm']))
        except (TypeError, ValueError):
            return api_response(None, 'distance_threshold_cm 必须为数字(厘米)', 400)
    if 'report_interval_ms' in data:
        try:
            dev.report_interval_ms = max(1000, int(data['report_interval_ms']))
        except (TypeError, ValueError):
            return api_response(None, 'report_interval_ms 必须为数字(毫秒)', 400)
    dev.is_new = False
    dev.last_seen = datetime.utcnow()
    db.session.commit()
    return api_response(dev.to_dict(), '设备配置已保存')


# ---------------------------------------------------------------------------
# AI：大模型服务（用户端 / 管理端 / 智能终端）
#
# 设计要点：
#  * 座位是否被占用由传感器+规则判定，AI 只做"翻译成人话"与"发现模式"；
#  * 未配置 API Key 或调用失败时，全部接口自动降级为规则文案，不会报错。
# ---------------------------------------------------------------------------

@app.route('/api/ai/status', methods=['GET'])
def ai_status():
    """AI 服务状态（不含密钥），供前端展示"AI 在线/降级中"。"""
    llm = get_llm()
    st = llm.status()
    st['mode'] = 'ai' if st['configured'] else 'fallback'
    st['mode_text'] = '大模型在线' if st['configured'] else '规则降级模式（未配置 API Key）'
    return api_response(st)


@app.route('/api/admin/ai/status', methods=['GET'])
@admin_required
def admin_ai_status():
    """管理端：AI 详细状态。"""
    return ai_status()


@app.route('/api/admin/ai/test', methods=['POST'])
@admin_required
def admin_ai_test():
    """管理端：连通性自检（点"测试 AI"按钮）。"""
    result = get_llm().test_connection()
    if result.get('ok'):
        return api_response(result, 'AI 连接正常')
    return api_response(result, result.get('reason') or 'AI 连接失败', 400)


@app.route('/api/admin/ai/reload', methods=['POST'])
@admin_required
def admin_ai_reload():
    """管理端：重载 AI 配置（改完 .env 后无需重启服务）。"""
    llm = reload_llm()
    reset_ai_services()
    return api_response(llm.status(), 'AI 配置已重载')


@app.route('/api/admin/ai/cache/clear', methods=['POST'])
@admin_required
def admin_ai_cache_clear():
    """管理端：清空 AI 结果缓存（强制下次重新生成）。"""
    n = get_llm().clear_cache()
    return api_response({'cleared': n}, f'已清空 {n} 条 AI 缓存')


# ------------------------------ 用户端 AI ------------------------------

@app.route('/api/ai/brief', methods=['GET'])
def ai_brief():
    """用户端"一句话结论"；也供智能终端（含 ESP32 OLED）轮询。

    查询参数：building_id / floor_id / max_len（终端可限制字数）
    """
    building_id = request.args.get('building_id', type=int)
    floor_id = request.args.get('floor_id', type=int)
    max_len = request.args.get('max_len', type=int)
    if max_len:
        result = terminal_brief(building_id=building_id, floor_id=floor_id, max_len=max_len)
    else:
        result = get_user_ai().brief(building_id=building_id, floor_id=floor_id)
    return api_response(result)


@app.route('/api/ai/habit', methods=['GET'])
@login_required
def ai_habit():
    """用户端：历史习惯总结。"""
    user = _load_current_user()
    return api_response(get_user_ai().habit_insight(user.id))


@app.route('/api/ai/explain', methods=['POST'])
@login_required
def ai_explain():
    """用户端：解释为什么推荐某个座位。"""
    data = request.get_json(silent=True) or {}
    seat_label = str(data.get('seat_label', '')).strip()
    if not seat_label:
        return api_response(None, '缺少 seat_label', 400)
    user = _load_current_user()
    result = get_user_ai().explain_recommendation(
        seat_label=seat_label,
        details=data.get('score_details') or {},
        user_id=user.id,
    )
    return api_response(result)


@app.route('/api/ai/ask', methods=['POST'])
@login_required
def ai_ask():
    """用户端：自然语言追问（如"有没有安静的座位？"）。"""
    data = request.get_json(silent=True) or {}
    user = _load_current_user()
    result = get_user_ai().ask(
        question=data.get('question', ''),
        user_id=user.id,
        building_id=data.get('building_id'),
        floor_id=data.get('floor_id'),
    )
    return api_response(result)


# ------------------------------ 管理端 AI ------------------------------

@app.route('/api/admin/ai/report', methods=['GET'])
@admin_required
def admin_ai_report():
    """管理端：运营简报（自然语言）。"""
    building_id = request.args.get('building_id', type=int)
    return api_response(get_admin_ai().daily_report(building_id=building_id))


@app.route('/api/admin/ai/anomaly', methods=['GET'])
@admin_required
def admin_ai_anomaly():
    """管理端：异常发现（把设备掉线/故障变成可读报告）。"""
    building_id = request.args.get('building_id', type=int)
    return api_response(get_admin_ai().anomaly_report(building_id=building_id))


@app.route('/api/admin/ai/trend', methods=['GET'])
@admin_required
def admin_ai_trend():
    """管理端：趋势解读（基于历史上报数据）。"""
    days = request.args.get('days', 7, type=int)
    building_id = request.args.get('building_id', type=int)
    return api_response(get_admin_ai().trend_analysis(days=days, building_id=building_id))


@app.route('/api/admin/ai/ask', methods=['POST'])
@admin_required
def admin_ai_ask():
    """管理端：自然语言问答。"""
    data = request.get_json(silent=True) or {}
    building_id = data.get('building_id')
    return api_response(get_admin_ai().ask(question=data.get('question', ''),
                                           building_id=building_id))


# ------------------------------ 智能终端 ------------------------------

@app.route('/terminal')
def terminal_page():
    """智能终端大屏页（Kiosk）：本机浏览器全屏打开即为"智能终端"。

    设计为免登录：终端通常摆放在公共区域，仅展示聚合信息与 AI 结论。
    页面零外部依赖（不引 CDN），断网也能正常渲染。
    """
    return render_template('terminal.html')


@app.route('/api/terminal/data', methods=['GET'])
def terminal_data():
    """智能终端一次性数据：AI 结论 + 座位网格 + 统计 + 可切换楼层（免登录）。

    位置解析顺序：URL 参数 > 管理员配置的终端默认位置 > 全部。
    """
    def _resolve(arg_name, config_name):
        """取参数；显式传 0 表示"不限"，未传则用管理员配置的默认位置。"""
        raw = request.args.get(arg_name)
        if raw is not None and str(raw).strip() != '':
            try:
                v = int(raw)
                return v if v > 0 else None
            except (TypeError, ValueError):
                return None
        v = int(getattr(Config, config_name, 0) or 0)
        return v if v > 0 else None

    building_id = _resolve('building_id', 'TERMINAL_BUILDING_ID')
    floor_id = _resolve('floor_id', 'TERMINAL_FLOOR_ID')
    use_ai = request.args.get('ai', '1') != '0'
    # seats_only=1：只返回座位/统计数据，不带 AI 文案。
    # 终端用它做高频刷新（约 2.5s 一次，实测仅 13ms）；AI 文案另按低频单独拉取，
    # 避免每次刷新都被大模型调用拖慢（首次调用可达 2.3s）。
    seats_only = request.args.get('seats_only', '0') == '1'

    snap = build_seat_snapshot(building_id=building_id, floor_id=floor_id)
    ai_text, ai_generated = None, False
    if use_ai and not seats_only:
        result = get_user_ai().brief(building_id=building_id, floor_id=floor_id)
        ai_text = result.get('text')
        ai_generated = result.get('ai_generated', False)
    if not seats_only and not ai_text:
        ai_text = _terminal_rule_text(snap)

    # 座位网格数据（供终端绘制色块）
    query = Seat.query.join(Floor).filter(Seat.is_active == True)  # noqa: E712
    if building_id:
        query = query.filter(Floor.building_id == building_id)
    if floor_id:
        query = query.filter(Floor.id == floor_id)
    seats = query.order_by(Seat.floor_id, Seat.seat_label).all()
    grid = [{'label': s.seat_label, 'status': s.status or 'free'} for s in seats]

    # 可切换的场所 / 楼层
    buildings = [
        {'id': b.id, 'name': b.name}
        for b in Building.query.filter_by(is_active=True).order_by(Building.id).all()
    ]
    fq = Floor.query.filter(Floor.is_active == True)  # noqa: E712
    if building_id:
        fq = fq.filter(Floor.building_id == building_id)
    floors = [
        {'id': f.id, 'name': (f.name or f'{f.floor_number}F')}
        for f in fq.order_by(Floor.building_id, Floor.floor_number).all()
    ]

    llm_status = get_llm().status()
    return api_response({
        'ai_text': ai_text,
        'ai_generated': ai_generated,
        'ai_mode': 'ai' if llm_status['configured'] else 'fallback',
        'title': getattr(Config, 'TERMINAL_TITLE', '智能座位导引'),
        'total': snap.get('total', 0),
        'free': snap.get('free', 0),
        'occupied': snap.get('occupied', 0),
        'error': snap.get('error', 0),
        'occupancy_rate': snap.get('occupancy_rate', 0),
        'data_stale': snap.get('data_stale', False),
        'last_report_minutes_ago': snap.get('last_report_minutes_ago'),
        'by_floor': snap.get('by_floor', {}),
        'seats': grid,
        'buildings': buildings,
        'floors': floors,
        'building_id': building_id,
        'floor_id': floor_id,
        'server_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    })


def _terminal_rule_text(snap):
    """终端用的规则兜底文案（与 ai_service 中口径一致）。"""
    from utils.ai_service import _fallback_brief
    return _fallback_brief(snap)


# ---------------------------------------------------------------------------
# 兼容：静态风格链接（xxx.html）在 Flask 下同样可用
#
# 背景：协作者的前端按「纯静态」习惯写链接（如 ../admin/buildings.html、
# seat_map.html）。由 Flask 提供服务时这些路径没有路由会 404。
# 这里补一层别名，只允许渲染确实存在的模板，避免目录穿越。
# ---------------------------------------------------------------------------
import re as _re

_SAFE_NAME = _re.compile(r'^[A-Za-z0-9_\-]+$')


def _render_static_alias(prefix, name):
    from jinja2 import TemplateNotFound
    from flask import abort
    if not _SAFE_NAME.match(name or ''):
        abort(404)
    try:
        return render_template('%s%s.html' % (prefix, name))
    except TemplateNotFound:
        abort(404)


@app.route('/admin/<name>.html')
def _admin_static_alias(name):
    return _render_static_alias('admin/', name)


@app.route('/<name>.html')
def _root_static_alias(name):
    return _render_static_alias('', name)


@app.route('/admin/students')
@admin_required
def admin_students_page():
    """学生管理页：批量导入 + 名单（管理员）"""
    return render_template('admin/students.html')


@app.route('/admin/ai')
@admin_required
def admin_ai_page():
    """管理端 AI 运营中心页。"""
    return render_template('admin/ai.html')


# ---------------------------------------------------------------------------
# 初始化数据库
# ---------------------------------------------------------------------------


def _ensure_sensor_device_columns():
    """轻量迁移（MySQL，幂等）：确保 sensor_devices 表包含 sensor_type / distance_threshold_cm 列。
    SQLite 由 db.create_all() 直接建全表，无需迁移。
    """
    if _try_mysql is False:
        return
    try:
        conn = db.engine.raw_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema=DATABASE() AND table_name='sensor_devices'"
            )
            cols = {r[0] for r in cur.fetchall()}
            added = []
            if 'sensor_type' not in cols:
                cur.execute("ALTER TABLE sensor_devices ADD COLUMN sensor_type VARCHAR(20) NOT NULL DEFAULT 'pir'")
                added.append('sensor_type')
            if 'distance_threshold_cm' not in cols:
                cur.execute("ALTER TABLE sensor_devices ADD COLUMN distance_threshold_cm INT NOT NULL DEFAULT 50")
                added.append('distance_threshold_cm')
            conn.commit()
            if added:
                logger.info('迁移：sensor_devices 表已添加列 %s', added)
    except Exception as e:
        logger.warning('sensor_devices 列迁移跳过: %s', e)


def _ensure_school_columns():
    """轻量迁移（MySQL，幂等）：给 buildings / users 补 school_id 列。

    schools 表由 db.create_all() 创建；已存在的表需要单独 ALTER。
    SQLite 由 db.create_all() 直接建全表，无需迁移。
    """
    if _try_mysql is False:
        return
    try:
        conn = db.engine.raw_connection()
        with conn.cursor() as cur:
            added = []
            for table in ('buildings', 'users'):
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema=DATABASE() AND table_name=%s", (table,)
                )
                cols = {r[0] for r in cur.fetchall()}
                if not cols:
                    continue          # 表还不存在，交给 create_all
                if 'school_id' not in cols:
                    cur.execute(
                        f"ALTER TABLE {table} ADD COLUMN school_id INT NULL, "
                        f"ADD INDEX idx_{table}_school (school_id)"
                    )
                    added.append(table)
            conn.commit()
            if added:
                logger.info('迁移：已为 %s 添加 school_id 列', added)
    except Exception as e:
        logger.warning('学校列迁移跳过: %s', e)


def init_database():
    """初始化数据库：建表，并首次创建超级管理员。"""
    with app.app_context():
        db.create_all()
        _ensure_sensor_device_columns()
        _ensure_school_columns()
        # 仅创建超级管理员（首次）
        if User.query.filter_by(role='super_admin').count() > 0:
            return
        from werkzeug.security import generate_password_hash
        admin_password = os.getenv('ADMIN_INITIAL_PASSWORD') or secrets.token_urlsafe(12)
        admin = User(
            student_id='admin', name='系统管理员', role='super_admin',
            is_approved=True, password_hash=generate_password_hash(admin_password))
        db.session.add(admin)
        db.session.commit()
        logger.warning('超级管理员 admin 已创建，初始密码为: %s', admin_password)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _get_stair_nodes(from_floor_id, to_floor_id):
    """获取跨层导航用的楼梯口节点映射 {楼层id: 楼梯节点id}"""
    stair_nodes = {}
    for floor_id in [from_floor_id, to_floor_id]:
        floor = Floor.query.get(floor_id)
        if not floor or not floor.road_network_path:
            continue
        network = RoadNetwork.load(floor.road_network_path)
        if not network:
            continue
        for node_id, node_data in network.nodes.items():
            if node_data.get('type') == 'stair':
                stair_nodes[floor_id] = node_id
                break
    return stair_nodes


_start_lock_sweeper()
_start_seat_sweeper()
_ensure_ir_enabled_column()


def _start_reservation_transition():
    global _reservation_transition_started
    if _reservation_transition_started:
        return
    _reservation_transition_started = True
    threading.Thread(target=_run_reservation_transition, daemon=True).start()


_reservation_transition_started = False
_start_reservation_transition()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    init_database()
    _autostart_sensor_simulator()
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
    socketio.run(app, debug=os.getenv('DEBUG', 'False').lower() == 'true',
                 host=bind_host, port=bind_port, allow_unsafe_werkzeug=True)

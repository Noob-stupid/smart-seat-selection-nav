"""
智能选座与导航一体化系统 - 配置文件
"""
import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'seat-nav-system-secret-key-2026')
    DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'

    # 模板自动重载
    # ------------------------------------------------------------------
    # Flask 在 DEBUG=False 下会把 templates/*.html 缓存在进程里，
    # 改了模板不重启服务就一直是旧页面（static/*.js、*.css 是实时读盘的，
    # 所以会出现「JS 生效了、页面没变」这种迷惑现象）。
    # 打开自动重载后，覆盖模板只需刷新页面，不必重启。
    TEMPLATES_AUTO_RELOAD = True

    # ------------------------------------------------------------------
    # 登录会话（手机 App 必须用持久 cookie）
    # ------------------------------------------------------------------
    # Flask 默认发的是「会话 cookie」——浏览器/WebView 进程一关就失效。
    # 安卓 App 每次冷启动都是新的 WebView 进程，于是每次打开都要重新登录。
    # 改成持久会话：cookie 带 Max-Age，App 重启后仍然保持登录。
    PERMANENT_SESSION_LIFETIME = timedelta(days=int(os.getenv('SESSION_DAYS', 30)))
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    # https 部署可在 .env 里设 SESSION_COOKIE_SECURE=1；
    # 默认关闭，否则本机 http:// 调试时 cookie 根本发不出去。
    SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', '0') == '1'

    # 文件上传
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB

    # MySQL 数据库
    DB_HOST = os.getenv('DB_HOST', '127.0.0.1')
    DB_PORT = int(os.getenv('DB_PORT', 3306))
    DB_USER = os.getenv('DB_USER', 'root')
    DB_PASSWORD = os.getenv('DB_PASSWORD', '')
    DB_NAME = os.getenv('DB_NAME', 'seat_navigation')
    # 密码中的 @ 需转义为 %40，避免被 URI 解析器误认为 user:password@host 分隔符
    _encoded_pw = DB_PASSWORD.replace('@', '%40')
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URL',
        f'mysql+pymysql://{DB_USER}:{_encoded_pw}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Redis 缓存
    REDIS_HOST = os.getenv('REDIS_HOST', '127.0.0.1')
    REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
    REDIS_DB = int(os.getenv('REDIS_DB', 0))
    REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', None)

    # 锁定参数默认值
    LOCK_M_DEFAULT = 20       # 锁定门槛 m（分钟）
    LOCK_N_DEFAULT = 5        # 检测周期 n（分钟）
    LOCK_T_DEFAULT = 30       # 最短有效回归时长 t（秒）
    LOCK_M_RANGE = (10, 60)   # m 可配置范围
    LOCK_N_RANGE = (2, 15)    # n 可配置范围
    LOCK_T_RANGE = (10, 120)  # t 可配置范围

    # AI 推荐权重
    AI_WEIGHTS = [0.35, 0.25, 0.25, 0.15]  # [dist, heat, pref, crowd]

    # 传感器配置
    SENSOR_SCAN_INTERVAL = 30  # 传感器扫描周期（秒）
    # 传感器模拟器开机自启（演示环境默认开启；接入真实硬件或 gunicorn 多 worker 时设为 False）
    SENSOR_SIMULATOR_AUTOSTART = os.getenv('SENSOR_SIMULATOR_AUTOSTART', 'True').lower() == 'true'

    # 签到配置
    CHECKIN_QR_ENABLED = False  # 二维码签到开关（默认关闭，由管理员在设置页开启）

    # 座位传感器离线扫描配置（管理员可在设置页修改）
    SEAT_OFFLINE_HOURS = 24             # 超过该时长未上报 -> 座位标记 error（小时）
    SEAT_SWEEP_INTERVAL_MINUTES = 30    # 离线扫描周期（分钟）
    # 「设备在线/离线」判定超时（分钟）。设备正常每 1 秒上报一次，
    # 几分钟无上报即可判离线。它与 SEAT_OFFLINE_HOURS 是两种语义：
    # 前者用于面板「在线/离线」显示，后者用于把座位标记为异常。
    SEAT_ONLINE_TIMEOUT_MINUTES = int(os.getenv('SEAT_ONLINE_TIMEOUT_MINUTES', '3'))

    # 掉线自动释放占用配置（管理员可在设置页修改）
    # 状态为 occupied 的座位，超过该分钟数无新上报 -> 自动释放为空闲
    # （防止设备掉线/换绑后座位停在占用，出现"没人却一直占用"）
    SEAT_RELEASE_OFFLINE_MINUTES = 5    # 占用座位超时未上报自动释放（分钟）

    # ==================== 大模型 AI 配置（外接 API，OpenAI 兼容协议） ====================
    # 说明：模型供应商可切换（deepseek / openai / custom），只需改 AI_PROVIDER，
    #      或直接显式指定 AI_BASE_URL + AI_MODEL 接入任意 OpenAI 兼容服务。
    AI_ENABLED = os.getenv('AI_ENABLED', 'True').lower() == 'true'

    # 供应商预设：base_url + 默认模型
    AI_PROVIDER_PRESETS = {
        'deepseek': {'base_url': 'https://api.deepseek.com/v1', 'model': 'deepseek-chat'},
        'openai':   {'base_url': 'https://api.openai.com/v1',   'model': 'gpt-4o-mini'},
        # 通义千问（阿里云 DashScope，OpenAI 兼容模式）
        'qwen':     {'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
                     'model': 'qwen-plus'},
        # 智谱 GLM（OpenAI 兼容模式）
        'zhipu':    {'base_url': 'https://open.bigmodel.cn/api/paas/v4',
                     'model': 'glm-4-flash'},
    }

    AI_PROVIDER = os.getenv('AI_PROVIDER', 'deepseek').strip().lower()
    _preset = AI_PROVIDER_PRESETS.get(AI_PROVIDER, {})
    AI_BASE_URL = os.getenv('AI_BASE_URL', _preset.get('base_url', '')).strip()
    AI_MODEL = os.getenv('AI_MODEL', _preset.get('model', '')).strip()

    # 密钥：优先 AI_API_KEY；未设置时回退到供应商同名变量（如 DEEPSEEK_API_KEY）
    AI_API_KEY = (
        os.getenv('AI_API_KEY', '').strip()
        or os.getenv(f'{AI_PROVIDER.upper()}_API_KEY', '').strip()
    )

    AI_TIMEOUT = int(os.getenv('AI_TIMEOUT', '20'))          # 单次请求超时（秒）
    AI_MAX_RETRIES = int(os.getenv('AI_MAX_RETRIES', '2'))   # 失败重试次数
    AI_MAX_TOKENS = int(os.getenv('AI_MAX_TOKENS', '600'))   # 单次生成 token 上限（控成本）
    AI_TEMPERATURE = float(os.getenv('AI_TEMPERATURE', '0.3'))
    AI_CACHE_TTL = int(os.getenv('AI_CACHE_TTL', '60'))      # 同快照结果缓存（秒），防重复调用

    # ==================== 室外导航地图（默认高德，管理员可换） ====================
    # 说明：JS API 的 key 属于「公开在前端的凭证」，但仍不应进公开仓库，
    #      因此只从环境变量 / 运行时配置读取，默认留空。
    # 高德 JS API v2 除 key 外通常还需要「安全密钥 securityJsCode」，
    #      若未配置，地图可能加载失败（表现为白屏）。
    NAV_MAP_PROVIDER = os.getenv('NAV_MAP_PROVIDER', 'amap').strip().lower()  # amap/baidu/none
    NAV_MAP_KEY = os.getenv('NAV_MAP_KEY', '').strip()
    NAV_MAP_SECURITY_CODE = os.getenv('NAV_MAP_SECURITY_CODE', '').strip()
    # 兜底：地图不可用（无 key / 断网 / 白名单未配）时，是否启用自建方位导航
    NAV_FALLBACK_ENABLED = os.getenv('NAV_FALLBACK_ENABLED', 'True').lower() == 'true'

    # ==================== 智能终端（Kiosk）显示位置 ====================
    # 管理员可指定这台终端摆放在哪个场所/楼层，终端页默认打开该位置；
    # 参观者仍可在终端上临时切换楼层查看。0 表示不限（显示全部）。
    TERMINAL_BUILDING_ID = int(os.getenv('TERMINAL_BUILDING_ID', '0') or 0)
    TERMINAL_FLOOR_ID = int(os.getenv('TERMINAL_FLOOR_ID', '0') or 0)
    TERMINAL_TITLE = os.getenv('TERMINAL_TITLE', '智能座位导引')   # 终端标题（可改成实际场馆名）

    # SQLite fallback（无 MySQL 时使用）
    SQLALCHEMY_DATABASE_URI_FALLBACK = 'sqlite:///seat_navigation.db'


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config_map = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}

# AI 诊断 504 超时的处理办法

## 现象

点「AI 诊断」，页面弹出：

```
504 Gateway Time-out
nginx
```

这是 **nginx 等不及了**，不是代码报错。

## 原因

AI 诊断要调 DeepSeek 分析这张图纸，一次请求通常十几到几十秒，
网络慢或模型排队时会更久。nginx 默认只等 60 秒，超了就自己回一个 504 页面 ——
请求其实还在后端跑，只是 nginx 不等了。

宝塔面板的站点配置里默认没有设这项，所以是 60 秒。

## 改法（宝塔面板）

打开 **网站 → zhinengzuo.site → 设置 → 配置文件**，
在 `location /`（或者 `location ~ /` 那段）**里面**加上三行：

```nginx
proxy_read_timeout   300s;
proxy_send_timeout   300s;
proxy_connect_timeout 300s;
```

改完的样子大概是：

```nginx
location / {
    proxy_pass http://127.0.0.1:5800;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # ↓ 加这三行：AI 诊断要跑几十秒，默认 60 秒会被 nginx 掐断
    proxy_read_timeout   300s;
    proxy_send_timeout   300s;
    proxy_connect_timeout 300s;
}
```

保存后 **不用重启 nginx**（宝塔会自动重载）。若没生效，点一下「重载配置」。

## 还要确认 gunicorn 的超时

nginx 放行了 300 秒，后面的 gunicorn 也得撑得住，两边要对齐：

```bash
ps aux | grep gunicorn | grep -v grep
```

看启动命令里有没有 `--timeout 300`。没有的话按下面重启：

```bash
cd /www/wwwroot/seatnav
pkill -f "venv/bin/gunicorn"
sleep 2
./venv/bin/gunicorn -k eventlet -w 1 -b 0.0.0.0:5800 app:app --daemon --timeout 300
sleep 3
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5800/api/status
```

## 验证

改完后点「AI 诊断」，正常应该：

- 按钮转圈十几到几十秒
- 然后面板里出现诊断结果（异常列表 + 建议）

如果还是 504，说明确实超过 300 秒了，那多半是 DeepSeek 那边的问题，
可以先在服务器上直接试：

```bash
cd /www/wwwroot/seatnav
time ./venv/bin/python -c "
import sys; sys.path.insert(0, '.')
from utils.ai_service import AIService
import config
s = AIService(config)
print('配置好了' if s else '没配')
"
```

## 备用方案

答辩现场网络不稳的话，AI 诊断不是必答项 —— 生成路网、座位、导航这些
都不依赖它。真出问题直接跳过，或者提前截好图放 PPT 里。

注意：AI 诊断面板里那句「模型未配置，以下为规则分析」是正常的降级提示，
规则部分（节点数、孤立点、骨架密度这些）不调模型也能算，照样能讲。

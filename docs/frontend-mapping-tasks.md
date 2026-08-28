# 前端任务：自动建图（手机拍摄/视频 → 平面图）

> 后端已完成 `view/auto_mapping` 接入主函数并上传，前端尚无对应实现。
> 本文档基于**真实可用**的后端接口，按优先级列出前端需要做的事。

## 一、后端已就绪的接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/admin/mapping/tasks` | 上传视频或图片组创建建图任务，同步执行，返回 `plane.json` 数据 |
| GET | `/api/admin/mapping/tasks/<task_id>` | 查询任务结果（刷新页面后恢复状态用） |
| POST | `/api/admin/mapping/tasks/<task_id>/apply` | 把结果绑定到指定楼层（body: `{"floor_id": 1}`） |
| GET | `/outputs/<path>` | 拼接图 / plane.json / 关键帧静态访问（如 `/outputs/room_xxx/stitched.jpg`） |

`POST /api/admin/mapping/tasks` 请求（multipart/form-data）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `file` | 文件 | 单视频（mp4/mov/avi/mkv/webm/m4v），或多张图片（重复字段名） |
| `mode` | 文本 | `video` / `images`；按文件扩展名自动判断，通常可不传 |
| `name` | 文本 | 房间名称，默认「自动建模房间」 |
| `line_method` | 文本 | `lsd`（默认）/ `hough` |

成功响应 `data`：

```json
{
  "task_id": "room_1a2b3c4d",
  "room": { "id": "room_1a2b3c4d", "name": "自动建模房间", "mode": "phone_capture" },
  "image": { "width": 1920, "height": 1080, "url": "/outputs/room_1a2b3c4d/stitched.jpg" },
  "lines": [
    { "x1": 10, "y1": 20, "x2": 300, "y2": 20, "angle": 0.0, "length": 290.0, "type": "wall" }
  ],
  "unit": "pixel",
  "line_count": 42
}
```

错误：`400` = 素材不足或拼接失败；`500` = 模块不可用（opencv/numpy 缺失）。

## 二、前端任务清单

### 1. 上传入口（`templates/uploading.html` + `static/js/uploading.js`）
- [ ] 增加「自动建图 / 手动上传」两种模式（现有 CAD 单图上传保留为手动模式）
- [ ] 自动建图模式：
  - 单视频 `<input type="file" accept="video/*">`
  - 多图 `<input type="file" accept="image/*" multiple>`
  - 房间名称输入框
- [ ] 用 `FormData` 调 `POST /api/admin/mapping/tasks`（`window.axios.post(url, formData)` 已支持 FormData）
- [ ] 处理中 UI：接口为**同步执行**，处理期间请求会挂起，需全屏 loading（“提取关键帧 → 全景拼接 → 墙体识别”）并禁用按钮
- [ ] 错误提示：400（素材不足/拼接失败）、500（依赖缺失）
- [ ] 允许选择已有楼层（复用现有 建筑物/楼层 下拉逻辑），用于 after-apply 跳转

### 2. 建图结果预览（建议放在 uploading 页结果区块）
- [ ] 渲染底图：`<image :href="image.url" :width="image.width" :height="image.height">`
- [ ] SVG 叠加墙线：`<line v-for="l in lines" :x1="l.x1" :y1="l.y1" :x2="l.x2" :y2="l.y2">`
- [ ] 坐标对齐：SVG `viewBox="0 0 width height"`，宽高取接口 `image.width/image.height`（像素坐标系）
- [ ] 展示元信息：房间名、线段数 `line_count`
- [ ] 图片缩放/移动端自适应（`max-width: 100%`）

### 3. 应用结果到楼层
- [ ] 调用 `POST /api/admin/mapping/tasks/<task_id>/apply`，body `{ "floor_id": <id> }`
- [ ] 成功后跳转 `/admin/floor-plan?floor_id=<id>`（现有页面，继续添加座位 / 生成路网）

### 4. 状态恢复
- [ ] 保存 `task_id`（localStorage 或 URL 参数）
- [ ] 刷新后调 `GET /api/admin/mapping/tasks/<task_id>` 恢复结果
- [ ] 404 = 任务已清理，清除本地状态并提示

### 5. 异常兜底
- [ ] 建图失败时提示原因，并引导进入现有「手动画路线」模式（无需新开发）

## 三、注意事项（重要）

1. **`lines` ≠ 路网**：`plane.json` 的 `lines` 是墙体线段（`x1/y1/x2/y2`），
   与现有路网接口的 `nodes/edges` 不是同一数据结构。**不要**把 `lines` 塞进
   `/api/admin/network/generate` 或 `save-manual`；路网仍按现有流程生成/手绘。
2. **线段修正（编辑）暂不支持**：后端暂无 `refine`（保存修改后的墙线）接口，
   如需“增/删/拖动墙线后保存”，需后端新增 `POST /api/admin/mapping/tasks/<task_id>/refine`。v1 可先只做预览。
3. `apply` 会把拼接图复制到 `uploads` 并更新楼层 `floor_plan_path/width/height`，之后旧页面逻辑（`floor_plan_url` 等）无需改动即可使用。
4. 上传体积：`Config.MAX_CONTENT_LENGTH` 为 100MB，前端超限需提示。

## 四、验收标准

- [ ] 上传视频/多图 → 显示处理中 → 展示拼接图与墙线
- [ ] 刷新页面可恢复上次建图结果
- [ ] apply 后跳转平面图配置页，楼层平面图正常显示
- [ ] 素材不足 / 依赖缺失时给出明确错误提示
- [ ] 现有手动上传（CAD 图）功能不受影响

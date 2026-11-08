# 非机动车识别与记录管理

YOLOv5 + OpenCV + Flask + SQLite 的本地课程项目，包含图片检测、摄像头实时预览、结果留存和车辆台账管理。

**版本说明：原课设完整版本未能确认，本仓库是2026年11月借助 AI 重新实现的展示版，参考了本机保留的旧 YOLOv5 工程功能。当前提交记录对应重建时间，不代表2025年的原始开发记录。**

## 功能与边界

- 图片上传、模型推理、边框及置信度展示，检测结果与图片保存到本地。
- 摄像头 MJPEG 实时检测预览，停止预览后释放设备；预览帧不自动入库。
- SQLite 车辆台账，新增、查询、修改、删除及分页；检测记录查询与删除。
- 上传大小、图片格式与像素数限制；参数化 SQL、字段校验、CSRF 保护。
- 模型延迟加载，推理使用线程锁；未准备好模型时可先使用车辆管理。

默认官方 COCO 预训练权重仅将 `bicycle` 作为目标。**不声称能区分电动自行车、三轮车或识别车牌**；台账编号由人工录入。如需细分类别，应准备自己的标注数据与训练权重，并使 `TARGET_CLASSES` 与权重标签一致。

## 快速运行

推荐 Python 3.10 / 3.11，在独立虚拟环境中安装：

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

打开 http://127.0.0.1:5000 。首次推理通过 PyTorch Hub 加载官方 `ultralytics/yolov5:v7.0` 的代码和 `yolov5s` 权重，需要网络。参考[官方 PyTorch Hub 文档](https://docs.ultralytics.com/yolov5/tutorials/pytorch-hub-model-loading/)。默认绑定本机，未提供公网多用户登录及部署方案。

## 本地权重 / 离线配置

可以自行从[官方 YOLOv5 仓库](https://github.com/ultralytics/yolov5)准备 v7.0 源码和对应权重，再通过环境变量指定。PowerShell 示例：

```powershell
$env:YOLOV5_REPO='C:\path\to\yolov5'
$env:YOLO_WEIGHTS='C:\path\to\yolov5s.pt'
$env:TARGET_CLASSES='bicycle'
$env:YOLO_CONFIDENCE='0.4'
$env:CAMERA_INDEX='0'
python app.py
```

只加载你信任的模型权重；模型、数据与 YOLOv5 上游代码不打包进本仓库，上游的许可与使用条件以其官方发布为准。PyTorch 与 torchvision 应使用匹配版本；推荐组合为 `torch==2.5.1` / `torchvision==0.20.1`。

## 结构与接口

- `app.py`：Flask 工厂、图片与视频路由、SQLite 数据管理。
- `detector.py`：YOLOv5 加载、类别过滤、推理与标注。
- `templates/`、`static/`：原生 HTML / CSS / JavaScript 页面。
- `tests/test_app.py`：接口及数据流程验证，不依赖下载权重。
- `runtime/`：运行后生成的数据库与图片，默认不进入 Git。

| 接口 | 功能 |
| --- | --- |
| `POST /api/detect` | 上传图片检测，multipart 字段 `image` |
| `GET /api/detections` | 查询最近100条检测记录 |
| `DELETE /api/detections/<id>` | 删除检测记录及图片 |
| `GET /api/vehicles?q=&page=1` | 车辆查询，每页50条 |
| `POST /api/vehicles` | 新增车辆 |
| `PUT /api/vehicles/<id>` | 修改车辆 |
| `DELETE /api/vehicles/<id>` | 删除车辆 |
| `GET /video_feed` | 服务器本机摄像头预览 |
| `GET /api/health` | 服务与模型加载状态 |

写入接口使用 `X-CSRF-Token`，由首页建立会话并提供令牌。车辆 JSON 字段为 `plate`、`vehicle_type`、`note`，其中前两项必填。

## 验证

```bash
python -m unittest discover -s tests -v
```

自动测试覆盖车辆 CRUD、重复编号、非法输入、CSRF、图片校验、检测结果存储与删除。摄像头链路需要真实设备手动验证；接口测试使用可控的推理替身，不作为真实模型精度证据。

2026-11-08 在 Python 3.11.8、PyTorch 2.5.1 CPU、torchvision 0.20.1、OpenCV 4.9 环境下通过4项接口测试，并使用本机官方 YOLOv5s 权重完成合成空白图片的真实推理冒烟检查。该检查确认模型调用链可运行，不构成非机动车识别准确率评估；本次未实测摄像头。

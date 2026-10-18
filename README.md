# edbo —— 化学反应贝叶斯优化平台

基于贝叶斯优化(Bayesian Optimization)的化学反应条件优化平台。它在经典的
[edbo](https://github.com/b-shields/edbo) 算法内核之上,叠加了一个完整的 Web 应用:
化学家可以在浏览器里定义反应空间、让算法推荐下一批实验、录入实验结果,并实时查看优化进展。

平台由三部分组成:

| 部分 | 目录 | 技术栈 |
|---|---|---|
| 算法内核 | [`edbo/`](edbo) | Python 包,GPyTorch 高斯过程 |
| 后端 | [`webapp/backend/`](webapp/backend) | FastAPI + SQLAlchemy/SQLite + dill 持久化 |
| 前端 | [`webapp/frontend/`](webapp/frontend) | React + Vite + TypeScript + Tailwind + Recharts |

---

## 一、功能概览

### 1. 算法内核(`edbo` 包)

| 能力 | 说明 |
|---|---|
| 反应空间构建 | 给定各组分取值,自动做笛卡尔积生成候选条件网格(`domain_index`) |
| 组分编码 | 独热 `ohe`、数值 `numeric`、名称解析 `resolve`(NIH 库)、`smiles`(Mordred 描述符)、自定义描述符矩阵 |
| 代理模型 | 高斯过程 `GP`(GPyTorch,默认)、随机森林 `RF`、贝叶斯线性、随机 |
| 采集函数 | TS / EI / PI / UCB,以及 `EI-TS`、`PI-TS`、`UCB-TS`、`MeanMax`、`VarMax` 等批量策略 |
| 初始采样 | `rand` 随机、`pam` k-medoids、`kmeans` 聚类、`external` 外部导入 |
| 结果分析 | 收敛曲线、预测 vs 实测、特征重要性等绘图工具 |
| 持久化 | 基于 `dill` 保存/恢复整个优化器 |

主要模块:[`bro.py`](edbo/bro.py)(`BO` / `BO_express`)、[`models.py`](edbo/models.py)、
[`acq_func.py`](edbo/acq_func.py)、[`init_scheme.py`](edbo/init_scheme.py)、
[`objective.py`](edbo/objective.py)、[`feature_utils.py`](edbo/feature_utils.py)。

### 2. Web 平台功能

**项目与反应空间**
- 项目创建、归档/恢复、配置克隆与重建
- 反应空间向导:组分取值配置、空间规模校验、规模上限保护(默认 500,000 点)

**描述符实验台**
- RDKit 2D / Mordred 2D 描述符在线计算(工具可用性自动检测)
- 自定义描述符 CSV 导入
- 特征选择、派生特征、标准化、PCA 降维
- What-if 非破坏性预览(对比改动前后模型的拟合效果),确认后一键 apply 重训

**优化闭环**
- 初始化:用随机 / pam / kmeans 采样生成首批实验,或导入已有前置实验结果直接训练模型
- 推荐榜:实时按所选采集函数给全空间候选排序(含预测均值/方差),一键采纳进当前轮
- 人机协同:机器建议的实验录入产率(留空 = 跳过);化学家也可手动添加条件,不在空间内的条件被拒绝、违反规则的条件仅告警
- 批次 CSV 往返:一键导出本轮推荐条件(产率可留空);实验完成后填好产率上传,程序逐条校验并回填到对应推荐或新增为本轮实验
- 条件排除规则引擎:用 AND 组合的条件子句排除化学上不可能的条件,并统计被排除的点数
- 任务化执行:建空间 / 训练 / 采集在后台任务中运行,前端轮询进度

**分析与修正**
- 历史与修正:修改已录入的产率会自动重建优化器并重训(只影响后续推荐,不改变历史记录)
- 分析面板:收敛曲线(按实验序 / 按轮次)、每轮产率分布、Top-N 最优条件、预测 vs 实测 R²
- 数据溯源:每条建议都记录"来源 + 采集函数 + 排名 + 当时使用的编码/描述符/模型"快照

---

## 二、目录结构

```
edbo/
├── edbo/                    # 算法内核(Python 包)
├── webapp/
│   ├── backend/             # FastAPI 后端
│   │   ├── app/             # 应用代码(路由、模型、服务、算法包装层)
│   │   ├── tests/           # 冒烟测试与仿真
│   │   ├── Dockerfile
│   │   └── requirements.docker.txt
│   ├── frontend/            # React 前端
│   │   ├── src/             # 页面与组件
│   │   ├── Dockerfile
│   │   └── nginx.conf
│   ├── docker-compose.yml   # 一键编排
│   └── DEPLOY.md            # 详细部署指南
├── docs/ examples/ experiments/ tests/   # 上游文档、示例与数据集
├── .dockerignore
└── setup.py
```

---

## 三、Docker 部署(推荐)

> 更完整的运维说明见 [`webapp/DEPLOY.md`](webapp/DEPLOY.md)。

### 1. 前置条件

- Docker Engine 20.10+ 与 Docker Compose v2(Docker Desktop 自带)
- 约 4 GB 磁盘(镜像内含 CPU 版 PyTorch 与 RDKit)
- 首次构建需联网下载依赖

```bash
docker --version
docker compose version
```

### 2. 快速开始

```bash
cd webapp
docker compose up -d --build
```

构建完成后访问:**http://localhost:8080**

> 网络受限或下载很慢时,可指定国内镜像源构建(后端镜像不使用 `apt`,无需访问 Debian 源):
>
> ```bash
> docker compose build \
>   --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
>   --build-arg NPM_CONFIG_REGISTRY=https://registry.npmmirror.com
> docker compose up -d
> ```

```bash
# 查看状态与日志
docker compose ps
docker compose logs -f backend

# 健康检查
curl http://localhost:8080/api/health      # 期望 {"status":"ok"}

# 停止(数据保留)
docker compose down
```

### 3. 部署架构

```
浏览器 :8080 → frontend(nginx)  ──/         → 静态 SPA(history 回退到 index.html)
                                 └─/api/…    → 反向代理 backend:8100
                                    backend(uvicorn,单 worker)
                                    └─ /srv/backend/data ← 命名卷 edbo_data
                                       (edbo.db / *.pkl / 描述符 *.csv)
```

- 前端始终调用相对路径 `/api/...`,由 nginx 反代,生产环境无需改代码。
- 后端**必须单 worker**(镜像内已固定 `--workers 1`):优化器缓存、每项目锁与后台任务都在进程内存中。

### 4. 数据持久化

容器内 `/srv/backend/data` 挂在命名卷 `edbo_data` 上,`docker compose down` 不会丢数据。

```bash
# 备份数据卷到当前目录(Windows 下把 $PWD 换成 %cd%)
docker run --rm -v edbo_data:/data -v "$PWD":/backup alpine tar czf /backup/edbo_data.tgz -C /data .

# 导入开发环境中已有的数据(注意 .pkl 的库版本兼容性)
docker compose up -d backend
docker compose cp ./backend/data/. backend:/srv/backend/data
docker compose restart backend
```

### 5. 常用运维命令

```bash
docker compose up -d --build            # 重建并启动
docker compose restart backend          # 重启后端
docker compose logs -f --tail=200       # 跟踪日志
docker compose exec backend bash        # 进入后端容器
docker compose exec backend python -c "import edbo, torch, gpytorch; print(torch.__version__, gpytorch.__version__)"
docker compose down -v                  # 停止并删除数据(慎用)
```

### 6. 可配置项

| 配置 | 位置 | 默认 |
|---|---|---|
| 对外端口 | 环境变量 `EDBO_PORT`(如 `EDBO_PORT=9000 docker compose up -d`) | `8080` |
| 直接暴露 API | `docker-compose.yml` 中 `backend.ports` 注释项 | 关闭 |
| 上传大小上限 | `frontend/nginx.conf` 的 `client_max_body_size` | 50m |
| 代理超时 | `frontend/nginx.conf` 的 `proxy_read_timeout` | 600s |
| 优化器内存缓存 | `backend/app/config.py` 的 `MAX_CACHED_INSTANCES` | 8 |
| 反应空间上限 | `backend/app/config.py` 的 `MAX_SPACE_SIZE` | 500000 |

### 7. 关于依赖版本

上游 `setup.py` 钉的是 2019 年的版本组合(`gpytorch==1.0.0`、`pyro-ppl==1.1`、`torch==1.3.1`),
在现代 Python 上无法安装。算法只使用 GPyTorch 的稳定公共 API,因此容器改用一组互相兼容且仍在维护的版本,
见 [`webapp/backend/requirements.docker.txt`](webapp/backend/requirements.docker.txt)(Python 3.9、CPU 版 PyTorch、
rdkit、gpytorch 1.11 等)。

> 描述符工具:RDKit 2D 与 Mordred 2D 均已内置(通过 `mordredcommunity` 提供 `mordred` 模块),edbo 的 `mordred` / `smiles` / `resolve` 编码因此可用。

### 8. 排错

| 现象 | 处理 |
|---|---|
| 构建报 `Failed to fetch http://deb.debian.org/...`(403 / 超时) | 镜像已不使用 `apt-get`,正常情况不会出现;仅当你自行加回 apt 时,才需按 `webapp/backend/Dockerfile` 注释换成可达镜像 |
| 建空间时报 `name 'Calculator' is not defined` | 镜像中缺少 Mordred(edbo 的 `mordred`/`smiles`/`resolve` 编码与“Mordred 2D”工具都依赖它)。当前版本已内置 `mordredcommunity`,重建后端即可:`docker compose build backend && docker compose up -d` |
| 依赖下载慢 / 卡在 `pip install` | 换国内索引:`docker compose build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`;前端可加 `--build-arg NPM_CONFIG_REGISTRY=https://registry.npmmirror.com`;PyTorch 轮子可用 `TORCH_INDEX_URL` 覆盖 |
| 页面报 502 | 后端尚未就绪,`docker compose logs backend` 查看启动日志 |
| 页面能开但接口 404 | 确认访问的是 nginx 端口(8080),而不是直接访问后端 |
| 某项目报 pickle 反序列化错误 | 库版本差异导致,重建该项目反应空间即可(历史 SQLite 数据不受影响) |

---

## 四、本地开发运行

不使用 Docker 时:

```bash
# 后端(仓库根目录)—— requirements.docker.txt 是完整的运行时依赖(含版本说明)
pip install -e .
pip install -r webapp/backend/requirements.docker.txt
cd webapp/backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8100 --workers 1

# 前端
cd webapp/frontend && npm install && npm run dev   # http://localhost:5173(Vite 自动代理 /api → 8100)
```

后端冒烟测试(用 FastAPI TestClient 跑完"建空间 → 初始化 → 录结果 → run → analytics"全流程):

```bash
cd webapp/backend
python -m pytest tests -q
```

---

## 五、引用与许可

本项目基于 Benjamin J. Shields 等人的 edbo 实现构建。

**Reference:** Shields, Benjamin J.; Stevens, Jason; Li, Jun; Parasram, Marvin; Damani, Farhan;
Janey, Jacob; Adams, Ryan P.; Doyle, Abigail G.
"Bayesian Reaction Optimization as A Tool for Chemical Synthesis".

**Upstream documentation:** https://b-shields.github.io/edbo/index.html

**License:** MIT(见 [`LICENSE`](LICENSE))。

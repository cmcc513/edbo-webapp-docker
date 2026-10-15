# edbo Web 平台 —— Docker 部署指南

本文档描述如何用 Docker / Docker Compose 部署本仓库的 edbo 化学反应贝叶斯优化平台。

平台由两部分组成:

| 容器 | 镜像 / 技术栈 | 作用 |
|---|---|---|
| `backend` | `python:3.9-slim` + FastAPI + edbo 算法内核 | 贝叶斯优化 REST API(端口 8100,仅内网) |
| `frontend` | `node:20` 构建 → `nginx:1.27` 运行 | 托管 React SPA,并把 `/api` 反向代理到 backend |

---

## 1. 前置条件

* Docker Engine 20.10+ 与 Docker Compose v2(Windows/macOS 上即 Docker Desktop)。
* 约 4 GB 磁盘(镜像含 CPU 版 PyTorch 与 RDKit)。
* 首次构建需要联网(下载 pip / npm 依赖)。

验证:

```bash
docker --version
docker compose version
```

---

## 2. 快速开始

```bash
# 进入 webapp 目录(compose 文件的所在位置)
cd webapp

# 构建并后台启动(首次约 5–15 分钟,主要耗时在 PyTorch/RDKit 下载与 npm 安装)
docker compose up -d --build

# 查看状态与日志
docker compose ps
docker compose logs -f backend
```

启动完成后访问:**http://localhost:8080**

健康检查:

```bash
curl http://localhost:8080/api/health     # 期望 {"status":"ok"}
```

停止 / 清理:

```bash
docker compose down          # 停止容器,数据卷 edbo_data 保留
docker compose down -v        # 停止并删除数据(不可恢复)
```

---

## 3. 目录结构(新增文件)

```
edbo/
├── .dockerignore                       # 构建上下文排除规则(仓库根目录)
├── setup.py                            # edbo 算法包安装脚本(被后端镜像使用)
├── edbo/                               # ★ 算法内核(被后端镜像 COPY 进去)
└── webapp/
    ├── docker-compose.yml              # ★ 一键编排
    ├── DEPLOY.md                       # ★ 本文档
    ├── backend/
    │   ├── Dockerfile                  # ★ 后端镜像
    │   └── requirements.docker.txt     # ★ 容器内 Python 依赖(见第 6 节说明)
    └── frontend/
        ├── Dockerfile                  # ★ 前端镜像(多阶段构建)
        └── nginx.conf                  # ★ 静态托管 + /api 反代
```

构建上下文是**仓库根目录** `edbo/`(而不是 `webapp/`),因为后端镜像需要把仓库根下的 `edbo` 算法包和 `setup.py` 安装进镜像。

---

## 4. 运行原理(容器视角)

```
浏览器  ──HTTP:8080──►  frontend (nginx)
                          │  /            → 静态文件(SPA,history 回退到 index.html)
                          │  /api/…       → 反向代理
                          ▼
                        backend (uvicorn, 127.0.0.1:8100, 单 worker)
                          │
                          ├── SQLite   /srv/backend/data/edbo.db
                          ├── pickle   /srv/backend/data/sessions/<project>.pkl
                          └── CSV      /srv/backend/data/descriptors/*.csv
                                        ▲
                                        └── 命名卷 edbo_data(持久化)
```

前端源码始终使用**相对路径** `/api/...`(见 `src/api/client.ts`),因此生产环境不需要改代码,由 nginx 负责把 `/api` 转发给 `backend` 容器。

> ⚠️ 后端必须**单 worker** 运行(镜像内已写死 `--workers 1`)。优化器的 LRU 缓存、每项目锁、`BackgroundTasks` 都在进程内存中,多 worker 会导致状态不一致。

---

## 5. 数据持久化与迁移

容器内的数据目录 `/srv/backend/data` 挂在命名卷 `edbo_data` 上,`docker compose down` 不会丢数据。

### 5.1 备份 / 恢复

```bash
# 备份:把卷内容打包到当前目录
docker run --rm -v edbo_data:/data -v "%cd%":/backup alpine \
  tar czf /backup/edbo_data.tgz -C /data .

# 恢复
docker run --rm -v edbo_data:/data -v "%cd%":/backup alpine \
  sh -c "rm -rf /data/* && tar xzf /backup/edbo_data.tgz -C /data"
```

(Linux/macOS 下把 `%cd%` 换成 `$PWD`。)

### 5.2 导入本机已有的开发数据

如果希望沿用开发环境里 `webapp/backend/data/` 的现有项目:

```bash
cd webapp
docker compose up -d backend            # 先让卷创建出来
docker compose cp ./backend/data/. backend:/srv/backend/data
docker compose restart backend
```

> ⚠️ 兼容性提示:`.pkl` 是本机 Python 3.9 + 特定 `dill`/`gpytorch` 版本序列化的。镜像也是 Python 3.9,但库版本不同,个别项目的 pickle 可能无法反序列化,表现为该项目操作报错。重新构建反应空间(`/rebuild` 或重新 `POST /space`)即可恢复正常;`edbo.db` 里的历史数据不受影响。
>
> 若只想要一个干净的实例,跳过本节即可(卷为空时首次启动会自动建库)。

---

## 6. 依赖版本说明(重要)

上游 `setup.py` 固定了 2019 年的版本组合:

```
gpytorch==1.0.0   pyro-ppl==1.1   (torch 1.3.1, Python 3.7)
```

这些 wheel 在现代 Python 上**无法安装**。算法代码只使用了 GPyTorch 的稳定公共 API(`ExactGP`、`MaternKernel`、`ScaleKernel`、`ConstantMean`、`GaussianLikelihood`、`ExactMarginalLogLikelihood`),因此容器改用一组互相兼容且仍在维护的版本,见 [`requirements.docker.txt`](backend/requirements.docker.txt):

| 包 | 版本 | 原因 |
|---|---|---|
| torch | `2.2.2+cpu` | 仅 CPU 轮子,避免 ~2.5 GB CUDA 依赖 |
| gpytorch | `1.11` | 与 torch 2.2 兼容 |
| linear_operator | `0.5.3` | gpytorch 1.11 的 settings 内部由它实现,锁到同期 0.5.x 保持 `_state` 标志兼容 |
| numpy | `1.26.4` | `<2`,兼容老科学计算栈 |
| scikit-learn | `1.2.2` | edbo 的 RF 模型使用 `max_features='auto'`,`>=1.3` 已移除该取值 |
| rdkit | `2023.9.6` | `edbo.feature_utils` 的硬性导入依赖 |
| pandas | `2.0.3` | 与 numpy 1.26 匹配 |

安装方式:后端镜像先用 CPU 索引安装 `torch`,再装其余依赖,最后以 `pip install --no-deps` 安装 edbo 本体(`--no-deps` 用于绕过上面那些不可用的 pin)。

**系统依赖:无需任何 `apt-get`。** 上面所有依赖都是自包含的 manylinux wheel——PyTorch 自带 OpenMP 运行时(`torch/lib/libgomp-*.so.1`)、matplotlib 自带 FreeType 且使用 Agg 后端、RDKit 自带第三方库、pyclustering 的 `setup.py` 不含 C 扩展(纯 Python 安装)。因此后端镜像中**没有 apt 步骤,构建过程不会访问 Debian 源**,在 `deb.debian.org` 被墙或不可达的网络下也能正常构建。

> 描述符工具:RDKit 2D 与 Mordred 2D 均已内置(`mordredcommunity` 提供 `mordred` 模块);edbo 的 `mordred` / `smiles` / `resolve` 编码因此可用。若自行移除该依赖,选择这些编码构建空间时会报 `name 'Calculator' is not defined`。

---

## 7. 可配置项

| 项目 | 位置 | 说明 |
|---|---|---|
| 对外端口 | 环境变量 `EDBO_PORT` | `EDBO_PORT=9000 docker compose up -d` |
| 直接暴露 API | `docker-compose.yml` 中 `backend.ports` 注释项 | 仪器/脚本直连时可打开 |
| 上传大小上限 | `frontend/nginx.conf` 的 `client_max_body_size` | 默认 50m |
| 代理超时 | `frontend/nginx.conf` 的 `proxy_read_timeout` | 默认 600s |
| 优化器内存缓存 | `backend/app/config.py` 的 `MAX_CACHED_INSTANCES` | 默认 8 个项目驻留内存 |
| 反应空间上限 | `backend/app/config.py` 的 `MAX_SPACE_SIZE` | 默认 500000 |
| 构建用包索引 | build-arg `PIP_INDEX_URL` / `TORCH_INDEX_URL` | 默认 `https://pypi.org/simple` 与 PyTorch 官方 CPU 索引 |
| 构建用 npm 源 | build-arg `NPM_CONFIG_REGISTRY`(frontend) | 默认 `https://registry.npmjs.org` |

修改 `config.py` 后需 `docker compose up -d --build backend` 重建。

---

## 8. 常用运维命令

```bash
cd webapp

docker compose up -d --build          # 重建并启动
docker compose restart backend        # 重启后端(重新加载 pickle)
docker compose logs -f --tail=200     # 跟踪全部日志
docker compose exec backend bash      # 进入后端容器
docker compose exec backend python -c "import edbo, torch, gpytorch; print(torch.__version__, gpytorch.__version__)"

# 更新代码后
docker compose build --no-cache backend && docker compose up -d backend
```

---

## 9. 生产环境建议

1. **HTTPS / 域名**:在 frontend 容器前再放一层网关(或直接在 nginx 里配置 TLS 证书),对外只暴露 443。
2. **收紧 CORS**:`backend/app/main.py` 目前是 `allow_origins=["*"]`。经 nginx 同源反代后已无跨域需求,建议改为具体域名。
3. **鉴权**:平台没有登录体系(`created_by` 默认 `anonymous`),只适合内网 / 可信网络。
4. **资源**:单机单实例。给 Docker 至少 4 GB 内存;大反应空间训练时 CPU 会吃满单核以上。
5. **不要横向扩容**:SQLite + 进程内状态决定了只能单副本。

---

## 10. 故障排查

| 现象 | 处理 |
|---|---|
| 构建报 `Failed to fetch http://deb.debian.org/...`(403 / 超时) | 镜像已不使用 `apt-get`,正常情况下不会出现;仅当你按注释自行加回 apt 时才需替换为可达镜像(见 `backend/Dockerfile` 注释) |
| 依赖下载慢 / 卡在 `pip install` | 换国内索引:`docker compose build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`;前端可加 `--build-arg NPM_CONFIG_REGISTRY=https://registry.npmmirror.com` |
| 构建失败在 `torch` | 确认能访问 `download.pytorch.org`;或用 `--build-arg TORCH_INDEX_URL=...` 指向可用的 CPU wheel 镜像 |
| 建空间时报 `name 'Calculator' is not defined` | 镜像缺少 Mordred(edbo 的 `mordred`/`smiles`/`resolve` 编码与“Mordred 2D”工具依赖它)。本版本已内置 `mordredcommunity`,重建后端:`docker compose build backend && docker compose up -d` |
| 打开页面报 502 | 后端还没就绪,`docker compose logs backend` 看启动日志;waiting 到 `/api/health` 返回 200 |
| 页面能开但接口 404 | 确认访问的是 nginx 的 8080 端口,而不是直接访问 backend |
| 某项目操作报 pickle 反序列化错误 | 见 5.2 的兼容性提示,重建该项目的反应空间 |
| 中文乱码 | 数据均为 UTF-8;确认浏览器/终端编码 |
| 需要更详细的 SQL 日志 | 在 compose 里给 backend 加 `SQLALCHEMY_WARN_20=1` 等环境变量并重启 |

---

## 11. 不使用 Docker 的运行方式(对照)

```bash
# 后端(仓库根目录)
pip install -e .
pip install -r webapp/backend/requirements.docker.txt
cd webapp/backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8100 --workers 1

# 前端
cd webapp/frontend && npm install && npm run dev    # http://localhost:5173(Vite 自动代理 /api → 8100)
```

Docker 部署与之等价,只是把「装依赖 + 起进程 + 反代」固化进了镜像。

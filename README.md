# 🎓 本专科分层实训多智能体学习辅导系统

**中国软件杯 A3赛道** | 科大讯飞出题

---

## 一、项目简介

面向**本科理论学习**与**专科高职实训**双群体的多智能体个性化学习平台。

### 核心特性
- 🔥 **双分支分层架构**：本科理论 + 专科实训，独立生成流水线
- 🤖 **6角色多智能体集群**：学情采集/诊断/路径规划/资源生成/校验/教师管理
- ⚔️ **三方辩论式资源校验**：生成Agent + 学生Agent + 教师Agent 并行评审
- 📱 **混合云边端离线部署**：PWA + IndexedDB，断网可用核心功能
- 📊 **教师管理大屏**：全班学情可视化、专项题库一键生成

---

## 二、技术栈

| 层级 | 技术 |
|---|---|
| 后端 | Python 3.12 / FastAPI / SQLAlchemy / LangChain |
| 前端 | React 18 / TypeScript / Zustand / ECharts / PWA |
| 数据库 | SQLite (开发) / PostgreSQL (生产) / ChromaDB (向量) |
| LLM | DeepSeek(主力) / Claude(把关) / 讯飞星火(门面) / 通义千问(备用) |
| 部署 | Docker Compose / Nginx |

---

## 三、快速启动

### 前置条件
- Python 3.12+
- Node.js 22+
- （可选）Redis

### 1. 后端

```bash
cd backend
cp .env.example .env
# 编辑 .env，填入至少一个 API Key（推荐 DeepSeek）
pip install -r requirements.txt
python run.py
```

后端运行在 http://localhost:8000

### 2. 前端

```bash
cd frontend
npm install
npm run dev
```

前端运行在 http://localhost:5173

### 3. Docker 一键部署

```bash
cp backend/.env.example backend/.env
# 编辑 backend/.env
docker-compose up -d
```

访问 http://localhost

---

## 四、系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                     前端 (React + PWA)                       │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────────┐ │
│  │ 学生端   │ │ 资源对比  │ │ 学习路径  │ │ 教师管理大屏     │ │
│  │ 聊天界面 │ │ 双分支展示│ │ 时间线    │ │ ECharts可视化    │ │
│  └────┬────┘ └────┬─────┘ └────┬─────┘ └───────┬─────────┘ │
│       │           │            │               │            │
│       │       Service Worker / IndexedDB (离线缓存)          │
└───────┼───────────┼────────────┼───────────────┼────────────┘
        │           │            │               │
        ▼           ▼            ▼               ▼
┌─────────────────────────────────────────────────────────────┐
│                   FastAPI 后端服务                           │
│  ┌───────────────┐ ┌──────────────┐ ┌───────────────────┐  │
│  │ 6 Agent 集群   │ │ LLM客户端     │ │ 多提供商路由       │  │
│  │ - 学情采集     │ │ - DeepSeek   │ │ - /api/dialogue   │  │
│  │ - 诊断分析     │ │ - Claude     │ │ - /api/resources  │  │
│  │ - 路径规划     │ │ - 讯飞星火   │ │ - /api/pathways   │  │
│  │ - 资源生成     │ │ - 通义千问   │ │ - /api/teacher    │  │
│  │ - 校验防幻觉   │ │              │ │ - /api/offline    │  │
│  │ - 教师管理     │ │              │ │                   │  │
│  └───────────────┘ └──────────────┘ └───────────────────┘  │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│                    数据层                                    │
│  ┌──────────────┐ ┌──────────────┐ ┌───────────────────┐   │
│  │ SQLite/      │ │ ChromaDB     │ │ Redis (缓存)       │   │
│  │ PostgreSQL   │ │ 向量检索      │ │                   │   │
│  └──────────────┘ └──────────────┘ └───────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 五、API 接口速览

| 接口 | 方法 | 说明 |
|---|---|---|
| `/api/students` | GET/POST | 学生注册与管理 |
| `/api/dialogue/chat` | POST | 对话交互（核心） |
| `/api/dialogue/chat/stream` | POST | 流式对话（SSE） |
| `/api/resources/generate` | POST | 资源生成 |
| `/api/resources/compare` | POST | 🔥 双分支对比生成 |
| `/api/resources/verify` | POST | 辩论校验 |
| `/api/pathways/generate` | POST | 学习路径生成 |
| `/api/teacher/overview` | POST | 全班学情分析 |
| `/api/teacher/exercises` | POST | 专项题库生成 |
| `/api/offline/cache/resources/{id}` | GET | 离线缓存数据 |

---

## 六、答辩演示流程

### 第1步：对话式学情画像自动构建（1分钟）
- 演示学生注册（分别选本科和专科）
- 对话过程自动更新6维画像

### 第2步：🔥 双分支对比演示（核心亮点，2分钟）
- 同一知识点"二叉树的遍历"
- 左边展示**本科版**（理论推导、复杂度分析）
- 右边展示**专科版**（代码实操、岗位应用）
- 肉眼可见的内容差异

### 第3步：辩论校验过程展示（1分钟）
- 展示学生Agent挑刺 → 教师Agent修正的过程
- 显示质量评分提升

### 第4步：离线模式演示（30秒）
- 断网后仍可浏览已缓存资源和错题

### 第5步：教师大屏展示（30秒）
- 全班学情统计 + 可视化图表

---

## 七、创新点总结（答辩必讲）

1. **双分支智能体分层架构** —— 赛道独家
2. **三方辩论式资源校验** —— 技术创新
3. **混合云边端离线部署** —— 工程落地

---

## 八、目录结构

```
中国软件杯/
├── backend/
│   ├── app/
│   │   ├── agents/          # 6个Agent实现
│   │   │   ├── collection_agent.py
│   │   │   ├── diagnosis_agent.py
│   │   │   ├── pathway_agent.py
│   │   │   ├── generation_agent.py
│   │   │   ├── verification_agent.py
│   │   │   └── teacher_agent.py
│   │   ├── api/             # FastAPI路由
│   │   ├── models/          # 数据库模型
│   │   ├── services/        # LLM客户端
│   │   └── db/              # 数据库配置
│   ├── requirements.txt
│   ├── .env.example
│   └── run.py
├── frontend/
│   ├── src/
│   │   ├── pages/           # 页面组件
│   │   ├── components/      # UI组件
│   │   ├── store/           # Zustand状态管理
│   │   ├── api/             # API客户端
│   │   ├── hooks/           # 自定义Hooks
│   │   └── utils/           # 离线DB工具
│   ├── package.json
│   └── vite.config.ts
├── docker/
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   └── nginx.conf
├── docker-compose.yml
└── README.md
```

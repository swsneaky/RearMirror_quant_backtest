# RearMirror 前端功能分层规划

## 一、功能模块总览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          RearMirror 前端功能全景                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                        Layer 1: 核心数据流                           │   │
│   │                                                                     │   │
│   │   数据配置 → 特征计算 → 中性化 → 模型训练 → 回测评估 → HPO优化      │   │
│   │       ↓           ↓         ↓          ↓          ↓          ↓      │   │
│   │   [ETL]      [Feature]  [Neutral]  [Model]   [Backtest]   [HPO]    │   │
│   │                                                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                      │                                      │
│   ┌──────────────────────────────────┴──────────────────────────────────┐   │
│   │                        Layer 2: 页面功能                             │   │
│   │                                                                     │   │
│   │   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │   │
│   │   │Dashboard │ │DataLayers│ │ Backtest │ │   HPO    │ │ Analysis │ │   │
│   │   │  概览    │ │  配置    │ │   回测   │ │   优化   │ │   分析   │ │   │
│   │   └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ │   │
│   │                                                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                      │                                      │
│   ┌──────────────────────────────────┴──────────────────────────────────┐   │
│   │                        Layer 3: 共享组件                             │   │
│   │                                                                     │   │
│   │   ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────────┐  │   │
│   │   │  图表组件   │ │  表格组件   │ │  表单组件   │ │    布局组件    │  │   │
│   │   │  Charts    │ │  Tables    │ │   Forms    │ │    Layouts     │  │   │
│   │   └────────────┘ └────────────┘ └────────────┘ └────────────────┘  │   │
│   │                                                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                      │                                      │
│   ┌──────────────────────────────────┴──────────────────────────────────┐   │
│   │                        Layer 4: 基础设施                             │   │
│   │                                                                     │   │
│   │   ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────────┐  │   │
│   │   │ API Client │ │  WebSocket │ │   Hooks    │ │   Zustand      │  │   │
│   │   │  REST/WS   │ │  实时推送   │ │  数据封装  │ │   状态管理     │  │   │
│   │   └────────────┘ └────────────┘ └────────────┘ └────────────────┘  │   │
│   │                                                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、Layer 1: 核心数据流 (后端能力)

这是后端已实现的能力，前端需要对接：

| 阶段 | 后端 API | 前端所需功能 | 当前状态 |
|------|---------|-------------|---------|
| **数据配置** | GET/PUT /api/config/etl | 指数选择、时间范围、股票上限 | ✅ 已实现 |
| **特征计算** | POST /api/tasks (task_type=data_update) | 触发数据更新任务 | ✅ 已实现 |
| **中性化** | GET/PUT /api/config/cross_section | MAD参数、行业最小股票数 | ✅ 已实现 |
| **模型训练** | POST /api/tasks (task_type=backtest) | 触发回测任务 | ⏳ 待实现 |
| **回测评估** | GET /api/backtest/results | 绩效指标、持仓、交易记录 | ⏳ 待实现 |
| **HPO优化** | GET /api/hpo/status, /api/hpo/trials | HPO状态、Trial列表 | ✅ 已实现 |
| **模型注册** | POST /api/models/register | 模型注册、晋升 | ⏳ 待实现 |

---

## 三、Layer 2: 页面功能规划

### 3.1 Dashboard (研究概览)

**定位**: 用户进入后的第一眼，快速了解当前研究状态

```
┌─────────────────────────────────────────────────────────────────┐
│  Dashboard                                                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐             │
│  │ 最新回测收益  │ │   夏普比率    │ │   最大回撤    │             │
│  │   +15.2%     │ │    1.81      │ │   -8.3%      │             │
│  │  vs 基准+5%  │ │   中等风险    │ │   控制良好    │             │
│  └──────────────┘ └──────────────┘ └──────────────┘             │
│                                                                  │
│  ┌─────────────────────────────┐ ┌───────────────────────────┐  │
│  │      数据资产状态            │ │      最近任务             │  │
│  │  ┌────────┬────────┐        │ │  • 数据更新  Running 45% │  │
│  │  │ 特征层 │ ✅最新  │        │ │  • HPO优化   Done       │  │
│  │  │ 标签层 │ ⚠需更新 │        │ │  • 回测      Failed     │  │
│  │  │ 模型层 │ ✅最新  │        │ │                           │  │
│  │  └────────┴────────┘        │ │                           │  │
│  └─────────────────────────────┘ └───────────────────────────┘  │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                      快捷操作                                ││
│  │  [新建回测]  [运行HPO]  [更新数据]  [查看报告]               ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**功能清单**:

| 功能 | 优先级 | 依赖 API | 状态 |
|------|--------|---------|------|
| 指标卡片 (收益/夏普/回撤) | P0 | GET /api/backtest/results | ⏳ |
| 数据资产状态 | P0 | GET /api/data-layers | ✅ |
| 最近任务列表 | P0 | GET /api/tasks | ✅ |
| 快捷操作入口 | P1 | - | ⏳ |

---

### 3.2 DataLayers (数据层管理)

**定位**: 配置数据、管理资产、触发任务

```
┌─────────────────────────────────────────────────────────────────┐
│  Data Layers                                                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────┐ ┌───────────────────────────┐  │
│  │      配置面板                │ │      任务进度             │  │
│  │                             │ │                           │  │
│  │  股票池: [zz500      ▼]     │ │  Task: data_update        │  │
│  │  时间: 2016-01 ~ 2026-03    │ │  Status: Running ██████░░ │  │
│  │  因子: [kline][rolling]...  │ │  Progress: 65%            │  │
│  │                             │ │  [取消]                   │  │
│  │  [保存配置] [更新数据]       │ │                           │  │
│  └─────────────────────────────┘ └───────────────────────────┘  │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                      数据层状态表                            ││
│  │  ┌──────────┬────────┬──────────┬──────────┬───────────┐   ││
│  │  │ 层名称    │ 输出   │ 指纹     │ 上游变化  │ 是否更新   │   ││
│  │  ├──────────┼────────┼──────────┼──────────┼───────────┤   ││
│  │  │ canonical│ ✅存在  │ ✅存在   │ ✅稳定    │ ✅当前    │   ││
│  │  │ feature  │ ✅存在  │ ✅存在   │ ⚠变化    │ ⚠需更新   │   ││
│  │  │ label    │ ✅存在  │ ✅存在   │ ✅稳定    │ ✅当前    │   ││
│  │  └──────────┴────────┴──────────┴──────────┴───────────┘   ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**功能清单**:

| 功能 | 优先级 | 依赖 API | 状态 |
|------|--------|---------|------|
| ETL配置编辑 | P0 | GET/PUT /api/config/etl | ✅ |
| 因子组选择 | P0 | GET/PUT /api/config/features | ✅ |
| 中性化参数 | P0 | GET/PUT /api/config/cross_section | ✅ |
| 触发数据更新任务 | P0 | POST /api/tasks | ✅ |
| 任务进度显示 | P0 | GET /api/tasks | ✅ |
| 数据层状态表 | P0 | GET /api/data-layers | ✅ |
| 缓存统计 | P1 | GET /api/data-layers/cache/stats | ✅ |

---

### 3.3 Backtest (回测工作台)

**定位**: 配置回测参数、运行回测、查看结果

```
┌─────────────────────────────────────────────────────────────────┐
│  Backtest                                                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────┐ ┌───────────────────────────┐  │
│  │      回测配置                │ │      运行控制             │  │
│  │                             │ │                           │  │
│  │  模型: [lightgbm  ▼]        │ │  训练期: 2016~2020        │  │
│  │  Walk-Forward: [5折 ▼]      │ │  测试期: 2021~2026        │  │
│  │  初始资金: 1,000,000        │ │                           │  │
│  │  滑点: 0.1%                 │ │  [运行回测]               │  │
│  │  手续费: 万三               │ │                           │  │
│  └─────────────────────────────┘ └───────────────────────────┘  │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                      NAV 曲线图                              ││
│  │                                                              ││
│  │     1.5 ┤                    ╭──────╮                        ││
│  │     1.2 ┤               ╭────╯      ╰───╮                   ││
│  │     1.0 ┤───────────────╯               ╰───                ││
│  │     0.8 ┤          ╭──╮                                     ││
│  │         └─────────────────────────────────────────          ││
│  │          2021    2022    2023    2024    2025               ││
│  │         ─── 策略NAV    ─ ─ 基准NAV                          ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
│  ┌───────────────────────┐ ┌───────────────────────────────────┐│
│  │     绩效指标           │ │          持仓分析                 ││
│  │  总收益: +52.1%       │ │  ┌─────┐ ┌─────┐ ┌─────┐         ││
│  │  年化收益: +12.3%     │ │  │科技 │ │金融 │ │消费 │         ││
│  │  夏普比率: 1.81       │ │  │ 35% │ │ 28% │ │ 22% │         ││
│  │  最大回撤: -8.3%      │ │  └─────┘ └─────┘ └─────┘         ││
│  │  胜率: 56.2%          │ │                                   ││
│  └───────────────────────┘ └───────────────────────────────────┘│
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**功能清单**:

| 功能 | 优先级 | 依赖 API | 状态 |
|------|--------|---------|------|
| 回测参数配置 | P0 | GET/PUT /api/config/backtest (新增) | ⏳ |
| 触发回测任务 | P0 | POST /api/tasks (task_type=backtest) | ⏳ |
| NAV曲线图 | P0 | GET /api/backtest/results | ⏳ (Mock) |
| 绩效指标卡片 | P0 | GET /api/backtest/results | ⏳ (Mock) |
| 持仓分析饼图 | P1 | GET /api/backtest/holdings (新增) | ⏳ |
| 交易记录表 | P1 | GET /api/backtest/trades (新增) | ⏳ |
| 收益归因 | P2 | GET /api/backtest/attribution (新增) | ⏳ |

---

### 3.4 HPO (超参优化)

**定位**: 监控HPO进度、查看优化结果

```
┌─────────────────────────────────────────────────────────────────┐
│  HPO Monitor                                                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐             │
│  │ 状态: 运行中  │ │ 进度: 15/50  │ │ 最佳: 1.81   │             │
│  │  🔄 Running   │ │   30%       │ │  Trial #12   │             │
│  └──────────────┘ └──────────────┘ └──────────────┘             │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                      Trial 结果表                            ││
│  │  ┌────────┬─────────┬──────────┬────────────────────────┐  ││
│  │  │ Trial  │  状态    │  Value   │      参数              │  ││
│  │  ├────────┼─────────┼──────────┼────────────────────────┤  ││
│  │  │   #12  │ ✅最佳   │  1.81    │ lr=0.15, depth=7      │  ││
│  │  │   #14  │ ✅完成   │  1.65    │ lr=0.12, depth=6      │  ││
│  │  │   #15  │ 🔄运行中 │   -      │ lr=0.18, depth=8      │  ││
│  │  │   #16  │ ⏳等待   │   -      │ -                      │  ││
│  │  └────────┴─────────┴──────────┴────────────────────────┘  ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                      最佳参数                                ││
│  │  {                                                          ││
│  │    "learning_rate": 0.15,                                   ││
│  │    "max_depth": 7,                                          ││
│  │    "n_estimators": 150                                      ││
│  │  }                                           [复制]         ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**功能清单**:

| 功能 | 优先级 | 依赖 API | 状态 |
|------|--------|---------|------|
| HPO状态卡片 | P0 | GET /api/hpo/status | ✅ |
| Trial结果表 | P0 | GET /api/hpo/trials | ✅ |
| 最佳参数展示 | P0 | GET /api/hpo/trials | ✅ |
| 自动刷新 (5s) | P0 | - | ✅ |
| 触发新HPO | P1 | POST /api/hpo/start (新增) | ⏳ |
| HPO配置 | P1 | GET/PUT /api/config/hpo (新增) | ⏳ |

---

### 3.5 Analysis (绩效分析) - 新增

**定位**: 深入分析回测结果

```
┌─────────────────────────────────────────────────────────────────┐
│  Analysis                                                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────┐ ┌───────────────────────────┐  │
│  │      收益分布                │ │      月度收益表           │  │
│  │                             │ │                           │  │
│  │      ▃▄▆█▆▄▃                │ │  2024: +5.2% +3.1% -1.2%  │  │
│  │     ▃▄▅▇█▇▅▄▃               │ │  2025: +8.1% +2.3% +4.5%  │  │
│  │    ▄▅▆██▇▅▃                 │ │                           │  │
│  │   -10%  0%  +10%            │ │  年度: +35.2%             │  │
│  └─────────────────────────────┘ └───────────────────────────┘  │
│                                                                  │
│  ┌─────────────────────────────┐ ┌───────────────────────────┐  │
│  │      行业暴露                │ │      Brinson归因          │  │
│  │                             │ │                           │  │
│  │  科技 ████████████ 35%      │ │  交互效应: +2.1%          │  │
│  │  金融 ████████ 28%          │ │  配置效应: +1.5%          │  │
│  │  消费 ██████ 22%            │ │  选择效应: +3.8%          │  │
│  │  其他 ███ 15%               │ │  总超额: +7.4%            │  │
│  └─────────────────────────────┘ └───────────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**功能清单**:

| 功能 | 优先级 | 依赖 API | 状态 |
|------|--------|---------|------|
| 收益分布图 | P2 | GET /api/backtest/returns (新增) | ⏳ |
| 月度/年度收益表 | P2 | GET /api/backtest/returns (新增) | ⏳ |
| 行业暴露分析 | P2 | GET /api/backtest/holdings (新增) | ⏳ |
| Brinson归因 | P3 | GET /api/backtest/attribution (新增) | ⏳ |

---

## 四、Layer 3: 共享组件规划

### 4.1 图表组件

```
components/charts/
├── NAVChart.tsx           # 净值曲线图 (带回撤)
├── KLineChart.tsx         # K线图 (可选)
├── ReturnDistribution.tsx  # 收益分布直方图
├── CorrelationMatrix.tsx   # 相关性矩阵热力图
├── ICChart.tsx            # IC/IR 柱状图
├── PieChart.tsx           # 饼图 (持仓分布)
├── WaterfallChart.tsx     # 瀑布图 (归因分析)
└── GaugeChart.tsx         # 仪表盘 (实时监控)
```

### 4.2 表格组件

```
components/tables/
├── TaskTable.tsx          # 任务列表表
├── TrialTable.tsx         # HPO Trial表
├── HoldingsTable.tsx      # 持仓表
├── TradesTable.tsx        # 交易记录表
└── FactorTable.tsx        # 因子列表表
```

### 4.3 表单组件

```
components/forms/
├── ConfigPanel.tsx        # 配置面板 (已实现)
├── DateRangePicker.tsx    # 日期范围选择 (已实现)
├── FactorGroupSelect.tsx  # 因子组多选 (已实现)
├── IndexSelect.tsx        # 指数选择
└── ModelSelect.tsx        # 模型选择
```

### 4.4 布局组件

```
components/layout/
├── Layout.tsx             # 整体布局 (已实现)
├── Header.tsx             # 顶部导航
├── Sidebar.tsx            # 侧边栏
├── MetricsCard.tsx        # 指标卡片
└── StatusBadge.tsx        # 状态徽章
```

---

## 五、Layer 4: 基础设施规划

### 5.1 API Client

```typescript
// api/client.ts - 已有基础，需扩展

export const api = {
  // 已实现
  health: () => apiGet('/health'),
  dataLayers: () => apiGet('/api/data-layers'),
  hpoStatus: () => apiGet('/api/hpo/status'),
  hpoTrials: () => apiGet('/api/hpo/trials'),
  
  // 配置 API (已实现)
  getETLConfig: () => apiGet('/api/config/etl'),
  updateETLConfig: (data) => apiPut('/api/config/etl', data),
  getFeaturesConfig: () => apiGet('/api/config/features'),
  updateFeaturesConfig: (data) => apiPut('/api/config/features', data),
  getCrossSectionConfig: () => apiGet('/api/config/cross_section'),
  updateCrossSectionConfig: (data) => apiPut('/api/config/cross_section', data),
  
  // 任务 API (已实现)
  createTask: (data) => apiPost('/api/tasks', data),
  getTasks: (status?) => apiGet(`/api/tasks${status ? `?status=${status}` : ''}`),
  getTask: (id) => apiGet(`/api/tasks/${id}`),
  cancelTask: (id) => apiPost(`/api/tasks/${id}/cancel`),
  
  // 回测 API (待实现)
  getBacktestResults: () => apiGet('/api/backtest/results'),
  getBacktestHoldings: () => apiGet('/api/backtest/holdings'),
  getBacktestTrades: () => apiGet('/api/backtest/trades'),
  
  // 模型 API (待实现)
  getModels: () => apiGet('/api/models/registry'),
  registerModel: (data) => apiPost('/api/models/register', data),
  promoteModel: (id) => apiPost(`/api/models/${id}/promote`),
};
```

### 5.2 WebSocket

```typescript
// api/websocket.ts - 待实现

type WSMessageType = 
  | 'task_progress'    // 任务进度更新
  | 'hpo_trial'        // 新 Trial 完成
  | 'backtest_result'  // 回测结果更新
  | 'system_notice';   // 系统通知

interface WSMessage<T> {
  type: WSMessageType;
  payload: T;
  timestamp: string;
}

export class WebSocketClient {
  private ws: WebSocket | null = null;
  private listeners: Map<WSMessageType, Set<(data: any) => void>> = new Map();
  
  connect(url: string): void;
  disconnect(): void;
  subscribe<T>(type: WSMessageType, handler: (data: T) => void): () => void;
  send<T>(type: WSMessageType, payload: T): void;
}
```

### 5.3 Hooks

```typescript
// hooks/index.ts - 已有基础，需扩展

// 数据 hooks (React Query) - 已实现
export function useDataLayers() { ... }
export function useHPOStatus() { ... }
export function useHPOTrials() { ... }
export function useTasks() { ... }
export function useETLConfig() { ... }
export function useFeaturesConfig() { ... }

// 待添加
export function useBacktestResults() { ... }
export function useBacktestHoldings() { ... }
export function useWebSocket() { ... }

// Mutation hooks - 已实现部分
export function useCreateTask() { ... }
export function useUpdateETLConfig() { ... }

// 待添加
export function useRunBacktest() { ... }
export function useRegisterModel() { ... }
```

### 5.4 Zustand Stores

```typescript
// stores/appStore.ts

interface AppState {
  // UI 状态
  sidebarOpen: boolean;
  theme: 'light' | 'dark' | 'system';
  
  // 用户偏好
  defaultIndex: string;
  defaultDateRange: { start: string; end: string };
  
  // 临时状态
  selectedFactors: string[];
  activeBacktestId: string | null;
  
  // Actions
  toggleSidebar: () => void;
  setTheme: (theme: string) => void;
  setDefaultIndex: (index: string) => void;
  setSelectedFactors: (factors: string[]) => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      sidebarOpen: true,
      theme: 'system',
      // ...
    }),
    { name: 'rearmirror-app' }
  )
);
```

---

## 六、实施优先级总览

```
Phase 1 (P0 - 1周内)
├── Dashboard 增强
│   ├── 指标卡片 (收益/夏普/回撤)
│   └── 快捷操作入口
├── Backtest 页面
│   ├── 连接真实后端 API
│   ├── NAV 曲线图
│   └── 绩效指标展示
└── 基础设施
    └── 扩展 api/client.ts

Phase 2 (P1 - 2周内)
├── WebSocket 实时推送
├── Backtest 增强
│   ├── 持仓分析
│   └── 交易记录表
└── HPO 增强
    ├── 触发新 HPO
    └── HPO 配置

Phase 3 (P2 - 1月内)
├── Analysis 页面
│   ├── 收益分布
│   ├── 月度/年度收益
│   └── 行业暴露
├── 图表组件库
│   ├── NAVChart
│   ├── ReturnDistribution
│   └── PieChart
└── Settings 页面

Phase 4 (P3 - 长期)
├── Brinson 归因
├── 高级图表
├── 响应式优化
└── 性能优化
```

---

## 七、文件结构规划

```
frontend/src/
├── app/
│   ├── App.tsx
│   ├── router.tsx              # 路由配置
│   └── providers.tsx           # Context Providers
│
├── pages/
│   ├── dashboard/
│   │   ├── index.tsx
│   │   ├── MetricsCard.tsx
│   │   └── QuickActions.tsx
│   ├── data-layers/
│   │   ├── index.tsx
│   │   └── LayerTable.tsx
│   ├── backtest/
│   │   ├── index.tsx
│   │   ├── BacktestConfig.tsx
│   │   ├── NAVChart.tsx
│   │   ├── MetricsPanel.tsx
│   │   └── HoldingsPie.tsx
│   ├── hpo/
│   │   ├── index.tsx
│   │   ├── HPOStatus.tsx
│   │   └── TrialTable.tsx
│   ├── analysis/
│   │   ├── index.tsx
│   │   ├── ReturnDistribution.tsx
│   │   └── MonthlyReturns.tsx
│   └── settings/
│       └── index.tsx
│
├── components/
│   ├── layout/
│   │   ├── Layout.tsx
│   │   ├── Header.tsx
│   │   ├── Sidebar.tsx
│   │   └── Footer.tsx
│   ├── charts/
│   │   ├── NAVChart.tsx
│   │   ├── PieChart.tsx
│   │   └── index.ts
│   ├── tables/
│   │   ├── TaskTable.tsx
│   │   └── index.ts
│   ├── forms/
│   │   ├── ConfigPanel.tsx
│   │   ├── DateRangePicker.tsx
│   │   ├── FactorGroupSelect.tsx
│   │   └── index.ts
│   └── ui/                     # shadcn/ui
│
├── hooks/
│   ├── index.ts
│   ├── useDataLayers.ts
│   ├── useBacktest.ts
│   ├── useHPO.ts
│   ├── useTasks.ts
│   ├── useWebSocket.ts
│   └── useConfig.ts
│
├── stores/
│   ├── index.ts
│   └── appStore.ts
│
├── api/
│   ├── client.ts
│   ├── websocket.ts
│   └── types.ts
│
├── lib/
│   ├── utils.ts
│   ├── formatters.ts           # 格式化函数
│   └── constants.ts
│
└── styles/
    └── globals.css
```

# RearMirror 前端顶层设计报告

## 一、主流量化交易平台前端特点对比

| 平台 | 前端技术栈 | 核心特点 | 可借鉴点 |
|------|-----------|---------|---------|
| **TradingView** | 自研图表引擎 + WebComponents | 专业K线图、多窗口布局、实时推送、自定义指标 | 图表组件化、多窗口Layout系统 |
| **QuantConnect** | React + Bootstrap | 云端IDE、策略编辑器、回测结果可视化 | 代码编辑器集成、任务队列UI |
| **WorldQuant BRAIN** | React + 自研UI | Alpha表达式编辑、实时排名、WebIDE | 表达式编辑器、竞赛榜单组件 |
| **聚宽** | Vue.js + ECharts | 策略研究、因子分析、回测报告 | 因子分析模块、研究报告UI |
| **米筐** | React + 自研 | 策略IDE、因子看板、实盘监控 | 因子看板、实盘状态组件 |
| **vnpy** | PyQt → Web(React/Vue) | 多策略管理、实盘交易、风控监控 | 多账户管理、交易终端UI |

### 核心共性设计模式

```
+------------------+------------------+------------------+
|   策略研究层      |   回测分析层      |   实盘交易层      |
+------------------+------------------+------------------+
| - 因子开发        | - 回测引擎        | - 策略监控        |
| - 数据探索        | - 绩效报告        | - 订单管理        |
| - 参数优化(HPO)   | - 风险分析        | - 风控预警        |
+------------------+------------------+------------------+
```

---

## 二、RearMirror 前端现状评估

### 2.1 技术栈分析

| 维度 | 当前选择 | 评估 |
|------|---------|------|
| **框架** | React 19.2.4 | 最新版本，长期支持 |
| **构建** | Vite 8.0.4 | 极快开发体验 |
| **样式** | TailwindCSS 4 + shadcn/ui | 现代化，可定制性强 |
| **状态管理** | Zustand 5.0 + React Query 5.99 | 轻量+服务端状态分离，优秀 |
| **图表** | ECharts 6.0 | 国产优秀，金融图表丰富 |
| **路由** | React Router 7.14 | 最新版本 |
| **主题** | next-themes | 支持暗色模式 |

### 2.2 当前页面结构

```
frontend/src/
├── App.tsx                 # 路由入口 (4 pages)
├── pages/
│   ├── Dashboard.tsx       # 导航卡片页 (较简单)
│   ├── DataLayers.tsx      # 数据层管理 ✅ 功能完整
│   ├── Backtest.tsx        # 回测工作台 (Mock数据)
│   └── HPO.tsx             # 超参优化监控 ✅ 功能完整
├── components/
│   ├── Layout.tsx          # Header + Sidebar
│   ├── ConfigPanel.tsx     # 配置编辑器 ✅
│   ├── TaskProgress.tsx    # 任务进度 ✅
│   └── ui/                 # shadcn 组件库
├── hooks/                  # React Query hooks
├── stores/                 # Zustand (仅sidebar状态)
└── api/client.ts           # API 类型定义完整 ✅
```

### 2.3 优点

1. **技术栈现代化**: React 19 + Vite 8 + TailwindCSS 4 均为最新版本
2. **类型定义完整**: `api/client.ts` 定义了完整的 TypeScript 类型
3. **状态管理清晰**: React Query 管理服务端状态，Zustand 管理 UI 状态
4. **组件库统一**: shadcn/ui 提供一致性 UI 基础
5. **API 抽象良好**: hooks 层封装完善

### 2.4 待改进

1. **Dashboard 页面过于简单**: 仅为导航卡片，缺乏概览数据
2. **Backtest 页面使用 Mock 数据**: 需要连接真实后端
3. **缺少核心功能页面**: 因子研究、绩效分析、持仓分析等
4. **图表功能薄弱**: 仅有简单 NAV 曲线，缺少专业金融图表
5. **无实时数据推送**: 缺少 WebSocket 集成

---

## 三、RearMirror 前端顶层设计

### 3.1 页面结构规划

```
App
├── /                        # Dashboard (研究概览)
│   ├── 指标卡片: 最新回测收益/夏普/最大回撤
│   ├── 数据资产状态卡片
│   ├── 最近任务列表
│   └── 快捷操作入口
│
├── /data-layers             # 数据层管理 ✅ 已实现
│   ├── 配置面板
│   ├── 数据层状态表格
│   └── 任务进度
│
├── /factors                 # 因子研究 (新增)
│   ├── 因子列表
│   ├── 因子相关性矩阵
│   ├── IC/IR 分析图表
│   └── 因子收益贡献
│
├── /backtest                # 回测工作台 (增强)
│   ├── 参数配置面板
│   ├── NAV 曲线图 (专业K线)
│   ├── 绩效指标表格
│   ├── 持仓分析
│   └── 收益归因分析
│
├── /hpo                     # 超参优化 ✅ 已实现
│
├── /analysis                # 绩效分析 (新增)
│   ├── 收益分布图
│   ├── 月度/年度收益表
│   ├── 行业暴露分析
│   └── Brinson 归因
│
└── /settings                # 系统设置 (新增)
    ├── API 配置
    ├── 主题设置
    └── 数据源配置
```

### 3.2 组件分层设计

```
┌─────────────────────────────────────────────────────────────┐
│                      Pages (页面层)                          │
│  Dashboard | DataLayers | Factors | Backtest | HPO | Analysis│
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                  Feature Components (功能组件)               │
│  ConfigPanel | FactorTable | BacktestChart | HPOTable       │
│  PerformanceMetrics | HoldingsTable | AttributionChart      │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                   Domain Components (领域组件)               │
│  KLineChart | NAVChart | CorrelationMatrix | ICHeatmap      │
│  MetricsCard | FactorCard | TradeTable | PositionView       │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                     UI Components (基础组件)                 │
│  Button | Card | Table | Tabs | Input | Select | Dialog    │
│  Badge | Tooltip | Progress | Skeleton | Toast              │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 状态管理方案

```
┌─────────────────────────────────────────────────────────────┐
│                  React Query (服务端状态)                    │
│  - Data Layers    - HPO Status     - Backtest Results       │
│  - Config         - Tasks          - Factor Analysis        │
│  - 自动缓存、后台刷新、乐观更新                                │
└─────────────────────────────────────────────────────────────┘
                              +
┌─────────────────────────────────────────────────────────────┐
│                   Zustand (客户端状态)                       │
│  - UI: sidebarOpen, theme, activeTab                        │
│  - 用户偏好: defaultIndex, dateRange                        │
│  - 临时状态: selectedFactors, chartConfig                   │
└─────────────────────────────────────────────────────────────┘
                              +
┌─────────────────────────────────────────────────────────────┐
│                  WebSocket (实时数据)                        │
│  - 实时任务进度                                              │
│  - HPO Trial 更新                                           │
│  - 回测进度                                                  │
└─────────────────────────────────────────────────────────────┘
```

### 3.4 数据可视化方案

| 图表类型 | 用途 | 推荐方案 |
|---------|------|---------|
| K线图 | 价格走势、交易信号 | ECharts candlestick |
| NAV曲线 | 策略净值、回撤 | ECharts line + area |
| 相关性矩阵 | 因子相关性 | ECharts heatmap |
| IC/IR图表 | 因子有效性 | ECharts bar + line |
| 持仓饼图 | 行业/风格分布 | ECharts pie |
| 收益归因 | Brinson归因 | ECharts waterfall |
| 实时监控 | 仪表盘 | ECharts gauge |

### 3.5 目录结构设计

```
frontend/src/
├── app/                      # 应用配置
│   ├── App.tsx
│   ├── router.tsx
│   └── providers.tsx
│
├── pages/                    # 页面
│   ├── dashboard/
│   ├── data-layers/
│   ├── factors/
│   ├── backtest/
│   ├── hpo/
│   ├── analysis/
│   └── settings/
│
├── features/                 # 功能模块 (按领域)
│   ├── config/
│   ├── tasks/
│   ├── backtest/
│   └── hpo/
│
├── components/               # 共享组件
│   ├── layout/
│   │   ├── Layout.tsx
│   │   ├── Header.tsx
│   │   ├── Sidebar.tsx
│   │   └── Footer.tsx
│   ├── charts/               # 图表组件
│   │   ├── KLineChart.tsx
│   │   ├── NAVChart.tsx
│   │   ├── CorrelationMatrix.tsx
│   │   └── ICChart.tsx
│   ├── tables/               # 表格组件
│   │   ├── FactorTable.tsx
│   │   ├── HoldingsTable.tsx
│   │   └── TradesTable.tsx
│   └── ui/                   # 基础UI组件
│
├── hooks/                    # 自定义Hooks
│   ├── useDataLayers.ts
│   ├── useBacktest.ts
│   ├── useWebSocket.ts
│   └── index.ts
│
├── stores/                   # Zustand Stores
│   ├── appStore.ts
│   ├── configStore.ts
│   └── index.ts
│
├── api/                      # API层
│   ├── client.ts
│   ├── websocket.ts
│   └── types.ts
│
├── lib/                      # 工具库
│   ├── utils.ts
│   ├── formatters.ts
│   └── constants.ts
│
└── styles/
    └── globals.css
```

---

## 四、架构设计图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              RearMirror Frontend                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         Presentation Layer                           │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │   │
│  │  │Dashboard │ │ Factors  │ │ Backtest │ │   HPO    │ │ Analysis │  │   │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘  │   │
│  │       │            │            │            │            │         │   │
│  │  ┌────┴────────────┴────────────┴────────────┴────────────┴────┐    │   │
│  │  │                 Feature Components                          │    │   │
│  │  │  ConfigPanel | TaskProgress | FactorTable | BacktestChart   │    │   │
│  │  └─────────────────────────────────────────────────────────────┘    │   │
│  │       │                                                              │   │
│  │  ┌────┴────────────────────────────────────────────────────────┐    │   │
│  │  │                   Domain Components                          │    │   │
│  │  │  KLineChart | NAVChart | CorrelationMatrix | MetricsCard    │    │   │
│  │  └─────────────────────────────────────────────────────────────┘    │   │
│  │       │                                                              │   │
│  │  ┌────┴────────────────────────────────────────────────────────┐    │   │
│  │  │                     UI Components (shadcn)                   │    │   │
│  │  │  Button | Card | Table | Tabs | Dialog | Badge | Input      │    │   │
│  │  └─────────────────────────────────────────────────────────────┘    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                      │                                      │
│  ┌───────────────────────────────────┴─────────────────────────────────┐   │
│  │                          State Layer                                 │   │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐  │   │
│  │  │  React Query    │  │    Zustand      │  │    WebSocket        │  │   │
│  │  │  (Server State) │  │  (Client State) │  │  (Real-time Data)   │  │   │
│  │  │                 │  │                 │  │                     │  │   │
│  │  │  - Data Layers  │  │  - sidebarOpen  │  │  - Task Progress    │  │   │
│  │  │  - Config       │  │  - theme        │  │  - HPO Updates      │  │   │
│  │  │  - HPO Status   │  │  - preferences  │  │  - Backtest Progress│  │   │
│  │  │  - Tasks        │  │                 │  │                     │  │   │
│  │  └────────┬────────┘  └────────┬────────┘  └──────────┬──────────┘  │   │
│  └───────────┼────────────────────┼─────────────────────┼──────────────┘   │
│              │                    │                     │                   │
│  ┌───────────┴────────────────────┴─────────────────────┴──────────────┐   │
│  │                           Data Layer                                 │   │
│  │  ┌──────────────────────────────────────────────────────────────┐   │   │
│  │  │                      API Client                               │   │   │
│  │  │  - REST API (fetch wrapper)                                   │   │   │
│  │  │  - Type definitions (TypeScript)                              │   │   │
│  │  │  - Error handling                                             │   │   │
│  │  └──────────────────────────────────────────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                      │                                      │
└──────────────────────────────────────┼──────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                              Backend (FastAPI)                                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │/health   │ │/api/data-│ │/api/hpo  │ │/api/back │ │/api/     │           │
│  │          │ │  layers  │ │          │ │  test    │ │  config  │           │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
│                                       │                                       │
│                              WebSocket /ws                                    │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 五、实施建议

### 5.1 优先级排序

| 优先级 | 任务 | 预估工时 |
|--------|------|---------|
| P0 | 完善 Backtest 页面连接真实后端 | 2d |
| P0 | 增强 Dashboard 为数据概览页 | 1d |
| P1 | 添加 WebSocket 实时推送 | 2d |
| P1 | 因子研究页面 | 3d |
| P2 | 绩效分析页面 | 3d |
| P2 | 专业图表组件库 | 2d |
| P3 | 响应式设计优化 | 2d |
| P3 | 系统设置页面 | 1d |

### 5.2 关键技术决策

1. **图表库**: 继续使用 ECharts，补充金融图表组件
2. **实时通信**: 使用原生 WebSocket，封装 `useWebSocket` hook
3. **表格性能**: 大数据量表格考虑 TanStack Virtual
4. **状态管理**: 保持当前架构 (React Query + Zustand)

### 5.3 WebSocket Hook 示例

```typescript
// hooks/useWebSocket.ts
export function useWebSocket<T>(url: string, onMessage: (data: T) => void) {
  const wsRef = useRef<WebSocket | null>(null);
  
  useEffect(() => {
    const ws = new WebSocket(url);
    ws.onmessage = (event) => onMessage(JSON.parse(event.data));
    wsRef.current = ws;
    return () => ws.close();
  }, [url]);
  
  return { send: (data: T) => wsRef.current?.send(JSON.stringify(data)) };
}
```

---

## 六、总结

RearMirror 前端已建立坚实的技术基础，技术栈选型现代化且合理。当前需要：

1. **功能补全**: 增加因子研究、绩效分析等核心功能页面
2. **数据连接**: Backtest 页面从 Mock 转为真实后端
3. **实时能力**: 集成 WebSocket 实现实时数据推送
4. **图表增强**: 构建专业的金融图表组件库

建议采用渐进式迭代，优先完成 P0 级别任务，逐步构建完整的量化研究前端平台。

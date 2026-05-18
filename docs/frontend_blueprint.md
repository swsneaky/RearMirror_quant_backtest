# Frontend Development Blueprint

## 1. 技术栈

| 层级 | 技术选择 | 说明 |
|------|----------|------|
| 前端框架 | React 18+ | 强制要求 |
| 构建工具 | Vite | 快速开发体验 |
| 状态管理 | Zustand | 轻量级，适合中小型应用 |
| 数据获取 | React Query | 缓存 + 自动刷新 |
| UI 组件 | Ant Design / shadcn/ui | 待定 |
| 图表库 | ECharts | 专业金融图表 |
| 样式 | TailwindCSS | 快速开发 |

## 2. 功能模块

### Phase 1: 数据层监控 (MVP)
- [ ] 数据层状态展示 (canonical / raw_feature)
- [ ] 缓存统计展示
- [ ] 刷新指纹功能

### Phase 2: 回测工作台
- [ ] 模型选择 (LightGBM / XGBoost / RandomForest)
- [ ] 回测参数调优面板
- [ ] 净值曲线图表
- [ ] 核心业绩指标卡片
- [ ] 特征重要性柱状图

### Phase 3: 结果浏览
- [ ] 迭代结果列表
- [ ] 简报详情展示
- [ ] 指标对比表格

### Phase 4: HPO 监控
- [ ] 优化进度展示
- [ ] Trial 结果列表
- [ ] 参数重要性图表

## 3. API 端点需求

### 已实现
- `GET /health` - 健康检查
- `GET /api/data-layers` - 数据层状态
- `GET /api/data-layers/{layer}` - 单层详情
- `POST /api/data-layers/refresh` - 刷新指纹
- `GET /api/data-layers/cache/stats` - 缓存统计

### 待实现
- `GET /api/backtest/run` - 运行回测
- `GET /api/backtest/results` - 回测结果
- `GET /api/iterations` - 迭代列表
- `GET /api/iterations/{id}` - 迭代详情
- `GET /api/hpo/status` - HPO 状态
- `GET /api/hpo/trials` - Trial 列表

## 4. 目录结构

```
frontend/
├── src/
│   ├── components/
│   │   ├── common/          # 通用组件
│   │   ├── charts/          # 图表组件
│   │   └── panels/          # 面板组件
│   ├── hooks/               # 自定义 hooks
│   ├── stores/              # Zustand stores
│   ├── api/                 # API 客户端
│   ├── pages/               # 页面组件
│   └── App.tsx
├── public/
├── package.json
└── vite.config.ts
```

## 5. 开发顺序

1. **初始化项目** - `npm create vite@latest frontend -- --template react-ts`
2. **配置基础依赖** - TailwindCSS, Zustand, React Query, ECharts
3. **实现 API 客户端** - 封装 fetch/axios
4. **开发 MVP 页面** - 数据层监控
5. **逐步扩展** - 回测工作台、结果浏览、HPO 监控

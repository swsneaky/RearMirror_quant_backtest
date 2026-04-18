import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface AppState {
  sidebarOpen: boolean;
  toggleSidebar: () => void;
}

export const useAppStore = create<AppState>((set) => ({
  sidebarOpen: true,
  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
}));

// ================================================================
// Stocks Page State (persisted to localStorage)
// ================================================================
interface StocksPageState {
  page: number;
  search: string;
  industry: string;
  sortBy: string;
  sortDesc: boolean;
  selectedCode: string | null;

  // Actions
  setPage: (page: number) => void;
  setSearch: (search: string) => void;
  setIndustry: (industry: string) => void;
  setSortBy: (sortBy: string) => void;
  setSortDesc: (sortDesc: boolean) => void;
  setSelectedCode: (code: string | null) => void;
  reset: () => void;
}

const defaultStocksState = {
  page: 1,
  search: '',
  industry: '',
  sortBy: 'code',
  sortDesc: false,
  selectedCode: null,
};

export const useStocksPageStore = create<StocksPageState>()(
  persist(
    (set) => ({
      ...defaultStocksState,
      setPage: (page) => set({ page }),
      setSearch: (search) => set({ search, page: 1 }),
      setIndustry: (industry) => set({ industry, page: 1 }),
      setSortBy: (sortBy) => set({ sortBy, page: 1 }),
      setSortDesc: (sortDesc) => set({ sortDesc }),
      setSelectedCode: (selectedCode) => set({ selectedCode }),
      reset: () => set(defaultStocksState),
    }),
    {
      name: 'rearmirror-stocks-page',
      partialize: (state) => ({
        page: state.page,
        search: state.search,
        industry: state.industry,
        sortBy: state.sortBy,
        sortDesc: state.sortDesc,
        // 不保存 selectedCode，因为抽屉状态不需要持久化
      }),
    }
  )
);

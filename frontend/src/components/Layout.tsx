import { Link, useLocation } from 'react-router-dom';
import { useAppStore } from '@/stores';
import { Database, Menu, X } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface LayoutProps {
  children: React.ReactNode;
}

export function Layout({ children }: LayoutProps) {
  const { sidebarOpen, toggleSidebar } = useAppStore();
  const location = useLocation();

  const navItems = [
    { path: '/', label: 'Dashboard' },
    { path: '/data-layers', label: 'Data Layers' },
    { path: '/stocks', label: 'Stocks' },
    { path: '/training-sets', label: 'Training Sets' },
    { path: '/model-training', label: 'Model Training' },
    { path: '/backtest', label: 'Backtest' },
    { path: '/hpo', label: 'HPO' },
    { path: '/factors', label: 'Factors' },
  ];

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="flex h-14 items-center px-4">
          <Button variant="ghost" size="icon" onClick={toggleSidebar} className="mr-2">
            {sidebarOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
          </Button>
          <Link to="/" className="flex items-center space-x-2">
            <Database className="h-6 w-6" />
            <span className="font-bold text-xl">RearMirror</span>
          </Link>
        </div>
      </header>

      <div className="flex">
        {/* Sidebar */}
        <aside
          className={`${
            sidebarOpen ? 'w-64' : 'w-0'
          } transition-all duration-300 border-r bg-muted/30 overflow-hidden`}
        >
          <nav className="p-4 space-y-2">
            {navItems.map((item) => (
              <Link
                key={item.path}
                to={item.path}
                className={`block px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  location.pathname === item.path
                    ? 'bg-primary text-primary-foreground'
                    : 'hover:bg-muted'
                }`}
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </aside>

        {/* Main content */}
        <main className="flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}

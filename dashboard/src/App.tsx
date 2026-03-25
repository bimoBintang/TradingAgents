import { useState, useEffect } from 'react';
import { Show, SignInButton, SignUpButton, UserButton, useUser } from '@clerk/react';
import { Sidebar } from './components/layout/Sidebar';
import { Select } from './components/ui/Select';
import { OverviewPage } from './pages/OverviewPage';
import { PositionsPage } from './pages/PositionsPage';
import { JournalPage } from './pages/JournalPage';
import { AnalysisPage } from './pages/AnalysisPage';
import { AgentConfigPage } from './pages/AgentConfigPage';
import { SystemSettingsPage } from './pages/SystemSettingsPage';
import { OfflinePage } from './pages/OfflinePage';
import { AdminOverviewPage } from './pages/admin/AdminOverviewPage';
import { UserManagementPage } from './pages/admin/UserManagementPage';
import { GlobalSettingsPage } from './pages/admin/GlobalSettingsPage';
import { AdminSidebar } from './components/layout/AdminSidebar';
import { Menu } from 'lucide-react';
import PendingOrderModal from './components/dashboard/PendingOrderModal';
import './index.css';

const ACCOUNT_OPTIONS = [
  { label: 'Paper Trading (Demo)', value: 'paper' },
  { label: 'Binance Live (API)', value: 'binance' },
  { label: 'Bybit Live (API)', value: 'bybit' },
];

function DashboardApp() {
  const { user, isLoaded } = useUser();
  
  const [userName, setUserName] = useState<string>('user');
  const [isAdmin, setIsAdmin] = useState(false);
  const [appMode, setAppMode] = useState<'user'|'admin'>('user');
  const [isOnline, setIsOnline] = useState(navigator.onLine);

  useEffect(() => {
    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  // Sync user profile from Clerk
  useEffect(() => {
    if (user) {
      setUserName((user.firstName || user.username || 'user').toLowerCase().replace(/\s+/g, '-'));
      // Check Clerk's public metadata for admin role
      const hasAdminRole = user.publicMetadata?.role === 'admin' || user.publicMetadata?.is_admin === true;
      setIsAdmin(!!hasAdminRole);
    }
  }, [user]);

  const [activeTab, setActiveTab] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    const view = params.get('view');
    if (view === 'analysis') return 'Analysis';
    if (view === 'positions') return 'Positions';
    if (view === 'journal') return 'Journal';
    if (view === 'ai-config') return 'AI Config';
    if (view === 'settings') return 'Settings';
    return 'Overview';
  });
  
  const [activeTicker, setActiveTicker] = useState('BTC-USD');
  const [tradingMode, setTradingMode] = useState('paper');
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  // Sync dashboard state to URL
  useEffect(() => {
    if (isLoaded && user) {
      const params = new URLSearchParams();
      params.set('view', activeTab.toLowerCase().replace(' ', '-'));
      params.set('workspace', `personal-${userName}`);
      params.set('mode', tradingMode);
      window.history.replaceState({}, '', `/dashboard?${params.toString()}`);
    }
  }, [isLoaded, user, activeTab, tradingMode, userName]);

  if (!isOnline) {
    return <OfflinePage />;
  }

  if (!isLoaded) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-slate-950 text-slate-100">
        <div className="flex flex-col items-center gap-4">
          <div className="w-12 h-12 border-4 border-blue-500/20 border-t-blue-500 rounded-full animate-spin"></div>
          <p className="text-sm text-slate-400 font-medium">Loading Identity...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-slate-950 text-slate-100 selection:bg-blue-500/30">
      
      {/* Mobile Sidebar Overlay */}
      {isSidebarOpen && (
        <div 
          className="fixed inset-0 bg-slate-950/80 backdrop-blur-sm z-40 lg:hidden"
          onClick={() => setIsSidebarOpen(false)}
        />
      )}

      {/* SIDEBAR - Conditionally user or admin */}
      {appMode === 'admin' ? (
        <AdminSidebar
          activeTab={activeTab}
          setActiveTab={(tab) => {
            setActiveTab(tab);
            setIsSidebarOpen(false);
          }}
          isOpen={isSidebarOpen}
        />
      ) : (
        <Sidebar 
          activeTab={activeTab} 
          setActiveTab={(tab) => {
            setActiveTab(tab);
            setIsSidebarOpen(false);
          }} 
          isOpen={isSidebarOpen}
        />
      )}

      {/* MAIN CONTENT */}
      <main className="flex-1 flex flex-col overflow-hidden relative">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,var(--tw-gradient-stops))] from-blue-900/20 via-slate-950 to-slate-950 -z-10" />

        {/* HEADER */}
        <header className="h-16 lg:h-20 px-4 lg:px-8 flex items-center justify-between border-b border-slate-800/50 bg-slate-950/50 backdrop-blur-md z-30 sticky top-0">
          <div className="flex items-center gap-3 lg:gap-6">
            <button 
              className="lg:hidden p-2 -ml-2 text-slate-400 hover:text-white transition-colors"
              onClick={() => setIsSidebarOpen(true)}
            >
              <Menu size={24} />
            </button>
            <h1 className="text-xl lg:text-2xl font-bold tracking-tight text-white line-clamp-1">{activeTab}</h1>
            
            <div className="hidden lg:block">
              <Select 
                options={ACCOUNT_OPTIONS}
                value={tradingMode}
                onChange={setTradingMode}
                className="w-52"
              />
            </div>
          </div>
          
          <div className="flex items-center gap-3 lg:gap-4">
            {isAdmin && (
              <button 
                onClick={() => {
                  setAppMode(m => m === 'admin' ? 'user' : 'admin');
                  setActiveTab(appMode === 'admin' ? 'Overview' : 'Admin Overview');
                }}
                className={`hidden sm:flex items-center gap-2 px-3 lg:px-4 py-1.5 lg:py-2 rounded-xl text-xs lg:text-sm font-bold border shadow-inner transition-all ${
                  appMode === 'admin' 
                    ? 'bg-blue-600/10 text-blue-400 border-blue-500/30 hover:bg-blue-600/20' 
                    : 'bg-amber-600/10 text-amber-400 border-amber-500/30 hover:bg-amber-600/20'
                }`}
              >
                {appMode === 'admin' ? 'Exit Admin Dashboard' : 'Switch to Admin Dashboard'}
              </button>
            )}

              <div className="shrink-0 flex items-center justify-center">
                <UserButton />
              </div>
            </div>
        </header>

        {/* SCROLL AREA */}
        <div className="flex-1 overflow-y-auto p-4 lg:p-8 z-0">
          {appMode === 'user' && activeTab === 'Overview' && (
            <OverviewPage activeTicker={activeTicker} setActiveTicker={setActiveTicker} />
          )}
          {appMode === 'user' && activeTab === 'Positions' && (
            <PositionsPage />
          )}
          {appMode === 'user' && activeTab === 'Analysis' && (
            <AnalysisPage />
          )}
          {appMode === 'user' && activeTab === 'Journal' && (
            <JournalPage />
          )}
          {appMode === 'user' && activeTab === 'AI Config' && (
            <AgentConfigPage />
          )}
          {appMode === 'user' && activeTab === 'Settings' && (
            <SystemSettingsPage />
          )}
          {appMode === 'admin' && activeTab === 'Admin Overview' && (
            <AdminOverviewPage />
          )}
          {appMode === 'admin' && activeTab === 'User Management' && (
            <UserManagementPage />
          )}
          {appMode === 'admin' && activeTab === 'Global Settings' && (
            <GlobalSettingsPage />
          )}
        </div>

        {/* Global Pending Order Confirmation Modal */}
        <PendingOrderModal />
      </main>
    </div>
  );
}

function App() {
  const { isLoaded } = useUser();

  if (!isLoaded) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-slate-950 text-slate-100">
        <div className="flex flex-col items-center gap-4">
          <div className="w-12 h-12 border-4 border-blue-500/20 border-t-blue-500 rounded-full animate-spin"></div>
          <p className="text-sm text-slate-400 font-medium">Loading Identity...</p>
        </div>
      </div>
    );
  }

  return (
    <>
      <Show when="signed-in">
        <DashboardApp />
      </Show>
      
      <Show when="signed-out">
        <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center p-4">
          <div className="mb-8 text-center">
            <h1 className="text-3xl font-bold bg-linear-to-r from-blue-400 to-cyan-300 bg-clip-text text-transparent mb-2">
              AegisTrade AI
            </h1>
            <p className="text-slate-400 text-sm mb-6">Sign in to access your intelligence dashboard</p>
            <div className="flex justify-center gap-4">
              <div className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-2.5 rounded-lg shadow-md transition-colors cursor-pointer font-medium">
                <SignInButton />
              </div>
              <div className="bg-slate-800 hover:bg-slate-700 border border-slate-700 text-white px-6 py-2.5 rounded-lg shadow-md transition-colors cursor-pointer font-medium">
                <SignUpButton />
              </div>
            </div>
          </div>
        </div>
      </Show>
    </>
  );
}

export default App;

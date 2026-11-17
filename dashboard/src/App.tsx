import { useState, useEffect } from 'react';
import { Sidebar } from './components/layout/Sidebar';
import { OverviewPage } from './pages/OverviewPage';
import { JournalPage } from './pages/JournalPage';
import { AgentConfigPage } from './pages/AgentConfigPage';
import { SystemSettingsPage } from './pages/SystemSettingsPage';
import { Menu } from 'lucide-react';
import PendingOrderModal from './components/dashboard/PendingOrderModal';
import './index.css';

function App() {
  const [activeTab, setActiveTab] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    const view = params.get('view');
    if (view === 'journal') return 'Journal';
    if (view === 'ai-config') return 'AI Config';
    if (view === 'settings') return 'Settings';
    return 'Overview';
  });
  
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  // Sync dashboard state to URL
  useEffect(() => {
    const params = new URLSearchParams();
    params.set('view', activeTab.toLowerCase().replace(' ', '-'));
    window.history.replaceState({}, '', `/dashboard?${params.toString()}`);
  }, [activeTab]);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-slate-950 text-slate-100 selection:bg-blue-500/30">
      
      {/* Mobile Sidebar Overlay */}
      {isSidebarOpen && (
        <div 
          className="fixed inset-0 bg-slate-950/80 backdrop-blur-sm z-40 lg:hidden"
          onClick={() => setIsSidebarOpen(false)}
        />
      )}

      <Sidebar
        activeTab={activeTab}
        setActiveTab={(tab) => {
          setActiveTab(tab);
          setIsSidebarOpen(false);
        }}
        isOpen={isSidebarOpen}
      />

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
          </div>
          
        </header>

        {/* SCROLL AREA */}
        <div className="flex-1 overflow-y-auto p-4 lg:p-8 z-0">
          {activeTab === 'Overview' && (
            <OverviewPage />
          )}
          {activeTab === 'Journal' && (
            <JournalPage />
          )}
          {activeTab === 'AI Config' && (
            <AgentConfigPage />
          )}
          {activeTab === 'Settings' && (
            <SystemSettingsPage />
          )}
        </div>

        {/* Global Pending Order Confirmation Modal */}
        <PendingOrderModal />
      </main>
    </div>
  );
}

export default App;

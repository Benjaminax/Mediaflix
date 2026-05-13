import { Home, Film, Tv, Search, Settings, ChevronLeft, ChevronRight, Plus, Clock } from 'lucide-react';
import { motion } from 'motion/react';
import { ViewType } from '../types';

interface SidebarProps {
  currentView: ViewType;
  onViewChange: (view: ViewType) => void;
  collapsed: boolean;
  onToggle: () => void;
}

export function Sidebar({ currentView, onViewChange, collapsed, onToggle }: SidebarProps) {
  const menuItems = [
    { icon: Home, label: 'Home', view: 'home' as ViewType },
    { icon: Search, label: 'Search', view: 'search' as ViewType },
    { icon: Film, label: 'Movies', view: 'movies' as ViewType },
    { icon: Tv, label: 'TV Shows', view: 'series' as ViewType },
    { icon: Clock, label: 'Recently Watched', view: 'home' as ViewType },
    { icon: Plus, label: 'My List', view: 'home' as ViewType },
  ];

  return (
    <motion.aside
      initial={false}
      animate={{ width: collapsed ? 80 : 280 }}
      className="fixed left-0 top-0 h-screen bg-[#141414] border-r border-[#2a2a2a] z-50 flex flex-col"
    >
      {/* Logo */}
      <div className="h-20 flex items-center justify-between px-6 border-b border-[#2a2a2a]">
        {!collapsed && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="text-[#E50914]"
          >
            MEDIAFLIX
          </motion.div>
        )}
        <button
          onClick={onToggle}
          className="p-2 hover:bg-[#2a2a2a] rounded-lg transition-colors ml-auto"
        >
          {collapsed ? (
            <ChevronRight className="w-5 h-5 text-[#B3B3B3]" />
          ) : (
            <ChevronLeft className="w-5 h-5 text-[#B3B3B3]" />
          )}
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-6">
        {menuItems.map((item) => {
          const Icon = item.icon;
          const isActive = currentView === item.view;
          
          return (
            <button
              key={item.label}
              onClick={() => onViewChange(item.view)}
              className={`w-full flex items-center gap-4 px-6 py-3 transition-all relative group ${
                isActive ? 'text-white' : 'text-[#B3B3B3] hover:text-white'
              }`}
            >
              {isActive && (
                <motion.div
                  layoutId="activeTab"
                  className="absolute left-0 w-1 h-8 bg-[#E50914] rounded-r"
                  transition={{ type: 'spring', stiffness: 380, damping: 30 }}
                />
              )}
              <div className={`${isActive ? 'bg-[#E50914]' : 'bg-transparent group-hover:bg-[#2a2a2a]'} p-2 rounded-lg transition-colors`}>
                <Icon className="w-5 h-5" />
              </div>
              {!collapsed && (
                <motion.span
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="whitespace-nowrap"
                >
                  {item.label}
                </motion.span>
              )}
            </button>
          );
        })}
      </nav>

      {/* Settings */}
      <div className="border-t border-[#2a2a2a] p-4">
        <button
          onClick={() => onViewChange('settings')}
          className={`w-full flex items-center gap-4 px-2 py-3 rounded-lg transition-colors ${
            currentView === 'settings'
              ? 'text-white bg-[#2a2a2a]'
              : 'text-[#B3B3B3] hover:text-white hover:bg-[#2a2a2a]'
          }`}
        >
          <Settings className="w-5 h-5" />
          {!collapsed && <span>Settings</span>}
        </button>
      </div>
    </motion.aside>
  );
}

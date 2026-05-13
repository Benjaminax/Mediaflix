import { motion } from 'motion/react';
import { User, Video, Bell, Shield, HardDrive, Palette, Globe } from 'lucide-react';
import { useState } from 'react';
import { Switch } from './ui/switch';

export function SettingsPage() {
  const [autoPlay, setAutoPlay] = useState(true);
  const [autoPlayNext, setAutoPlayNext] = useState(true);
  const [notifications, setNotifications] = useState(true);
  const [hdStreaming, setHdStreaming] = useState(true);

  const settingsSections = [
    {
      icon: User,
      title: 'Account',
      description: 'Manage your account settings and preferences',
    },
    {
      icon: Video,
      title: 'Playback',
      description: 'Control video playback behavior',
    },
    {
      icon: Bell,
      title: 'Notifications',
      description: 'Manage notification preferences',
    },
    {
      icon: HardDrive,
      title: 'Library',
      description: 'Configure media library and scanning',
    },
    {
      icon: Palette,
      title: 'Appearance',
      description: 'Customize interface themes and layout',
    },
    {
      icon: Shield,
      title: 'Privacy & Security',
      description: 'Control privacy and security settings',
    },
    {
      icon: Globe,
      title: 'Network',
      description: 'Configure network and streaming settings',
    },
  ];

  return (
    <div className="min-h-screen bg-[#141414] pt-20 px-16 pb-16">
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <h1 className="text-white mb-4">Settings</h1>
        <p className="text-[#B3B3B3] mb-12">
          Manage your Mediaflix preferences and settings
        </p>
      </motion.div>

      {/* Quick Settings */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="bg-[#181818] rounded-lg p-8 mb-8"
      >
        <h2 className="text-white mb-6">Quick Settings</h2>
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-white mb-1">Auto-play trailers</p>
              <p className="text-[#B3B3B3] text-sm">
                Automatically play trailers when browsing content
              </p>
            </div>
            <Switch checked={autoPlay} onCheckedChange={setAutoPlay} />
          </div>

          <div className="flex items-center justify-between">
            <div>
              <p className="text-white mb-1">Auto-play next episode</p>
              <p className="text-[#B3B3B3] text-sm">
                Automatically start the next episode when one finishes
              </p>
            </div>
            <Switch checked={autoPlayNext} onCheckedChange={setAutoPlayNext} />
          </div>

          <div className="flex items-center justify-between">
            <div>
              <p className="text-white mb-1">Notifications</p>
              <p className="text-[#B3B3B3] text-sm">
                Get notified about new content and updates
              </p>
            </div>
            <Switch checked={notifications} onCheckedChange={setNotifications} />
          </div>

          <div className="flex items-center justify-between">
            <div>
              <p className="text-white mb-1">HD Streaming</p>
              <p className="text-[#B3B3B3] text-sm">
                Stream content in high definition when available
              </p>
            </div>
            <Switch checked={hdStreaming} onCheckedChange={setHdStreaming} />
          </div>
        </div>
      </motion.div>

      {/* Settings Categories */}
      <div className="grid grid-cols-2 gap-6">
        {settingsSections.map((section, index) => {
          const Icon = section.icon;
          return (
            <motion.button
              key={section.title}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 + index * 0.05 }}
              className="bg-[#181818] hover:bg-[#2a2a2a] rounded-lg p-6 text-left transition-all hover:scale-[1.02] group"
            >
              <div className="flex items-start gap-4">
                <div className="w-12 h-12 rounded-lg bg-[#E50914]/10 flex items-center justify-center flex-shrink-0 group-hover:bg-[#E50914]/20 transition-colors">
                  <Icon className="w-6 h-6 text-[#E50914]" />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-white mb-2 group-hover:text-[#E50914] transition-colors">
                    {section.title}
                  </h3>
                  <p className="text-[#B3B3B3] text-sm">{section.description}</p>
                </div>
              </div>
            </motion.button>
          );
        })}
      </div>

      {/* Playback Quality */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.6 }}
        className="bg-[#181818] rounded-lg p-8 mt-8"
      >
        <h2 className="text-white mb-6">Playback Quality</h2>
        <div className="grid grid-cols-4 gap-4">
          {['Auto', '720p', '1080p', '4K'].map((quality) => (
            <button
              key={quality}
              className="bg-[#2a2a2a] hover:bg-[#E50914] text-white py-4 rounded-lg transition-all hover:scale-105"
            >
              {quality}
            </button>
          ))}
        </div>
      </motion.div>

      {/* About */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.7 }}
        className="bg-[#181818] rounded-lg p-8 mt-8"
      >
        <h2 className="text-white mb-6">About Mediaflix</h2>
        <div className="space-y-2 text-[#B3B3B3]">
          <p>Version 1.0.0</p>
          <p>© 2024 Mediaflix. All rights reserved.</p>
          <p className="mt-4 text-sm">
            Mediaflix is a modern streaming platform for managing and enjoying your personal media
            library.
          </p>
        </div>
      </motion.div>
    </div>
  );
}

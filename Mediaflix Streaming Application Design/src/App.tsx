import { useState } from 'react';
import { AnimatePresence } from 'motion/react';
import { Sidebar } from './components/Sidebar';
import { HomePage } from './components/HomePage';
import { SearchPage } from './components/SearchPage';
import { SettingsPage } from './components/SettingsPage';
import { DetailPage } from './components/DetailPage';
import { EpisodesView } from './components/EpisodesView';
import { VideoPlayer } from './components/VideoPlayer';
import { mockMediaData } from './data/mockData';
import { ViewType, MediaItem, Episode } from './types';

export default function App() {
  const [currentView, setCurrentView] = useState<ViewType>('home');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [selectedMedia, setSelectedMedia] = useState<MediaItem | null>(null);
  const [showEpisodes, setShowEpisodes] = useState(false);
  const [showPlayer, setShowPlayer] = useState(false);

  const handlePlay = (media: MediaItem) => {
    setSelectedMedia(media);
    setShowPlayer(true);
  };

  const handleInfo = (media: MediaItem) => {
    setSelectedMedia(media);
    setCurrentView('detail');
  };

  const handleCloseDetail = () => {
    setSelectedMedia(null);
    setCurrentView('home');
  };

  const handleShowEpisodes = () => {
    setShowEpisodes(true);
  };

  const handlePlayEpisode = (episode: Episode) => {
    setShowPlayer(true);
  };

  const handleClosePlayer = () => {
    setShowPlayer(false);
  };

  const getFilteredContent = () => {
    switch (currentView) {
      case 'movies':
        return mockMediaData.filter((item) => item.type === 'movie');
      case 'series':
        return mockMediaData.filter((item) => item.type === 'series');
      default:
        return mockMediaData;
    }
  };

  return (
    <div className="min-h-screen bg-[#141414]">
      <Sidebar
        currentView={currentView}
        onViewChange={setCurrentView}
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
      />

      <main
        className="transition-all duration-300"
        style={{
          marginLeft: sidebarCollapsed ? 80 : 280,
        }}
      >
        <AnimatePresence mode="wait">
          {currentView === 'home' && !selectedMedia && (
            <HomePage
              key="home"
              items={mockMediaData}
              onPlay={handlePlay}
              onInfo={handleInfo}
            />
          )}

          {currentView === 'movies' && (
            <HomePage
              key="movies"
              items={getFilteredContent()}
              onPlay={handlePlay}
              onInfo={handleInfo}
            />
          )}

          {currentView === 'series' && (
            <HomePage
              key="series"
              items={getFilteredContent()}
              onPlay={handlePlay}
              onInfo={handleInfo}
            />
          )}

          {currentView === 'search' && (
            <SearchPage
              key="search"
              items={mockMediaData}
              onPlay={handlePlay}
              onInfo={handleInfo}
            />
          )}

          {currentView === 'settings' && <SettingsPage key="settings" />}

          {currentView === 'detail' && selectedMedia && !showEpisodes && (
            <DetailPage
              key="detail"
              media={selectedMedia}
              onClose={handleCloseDetail}
              onPlay={() => handlePlay(selectedMedia)}
              onShowEpisodes={
                selectedMedia.type === 'series' ? handleShowEpisodes : undefined
              }
            />
          )}
        </AnimatePresence>

        {/* Episodes Modal */}
        <AnimatePresence>
          {showEpisodes && selectedMedia && selectedMedia.type === 'series' && (
            <EpisodesView
              key="episodes"
              media={selectedMedia}
              onClose={() => setShowEpisodes(false)}
              onPlayEpisode={handlePlayEpisode}
            />
          )}
        </AnimatePresence>

        {/* Video Player Modal */}
        <AnimatePresence>
          {showPlayer && selectedMedia && (
            <VideoPlayer
              key="player"
              media={selectedMedia}
              onClose={handleClosePlayer}
            />
          )}
        </AnimatePresence>
      </main>

      <style>{`
        .scrollbar-hide::-webkit-scrollbar {
          display: none;
        }
        .scrollbar-hide {
          -ms-overflow-style: none;
          scrollbar-width: none;
        }
      `}</style>
    </div>
  );
}

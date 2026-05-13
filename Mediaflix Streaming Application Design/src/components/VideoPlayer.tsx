import { motion, AnimatePresence } from 'motion/react';
import {
  Play,
  Pause,
  Volume2,
  VolumeX,
  Maximize,
  Settings,
  SkipBack,
  SkipForward,
  X,
  Minimize,
  Subtitles,
  Cast,
} from 'lucide-react';
import { useState, useEffect } from 'react';
import { MediaItem } from '../types';

interface VideoPlayerProps {
  media: MediaItem;
  onClose: () => void;
}

export function VideoPlayer({ media, onClose }: VideoPlayerProps) {
  const [isPlaying, setIsPlaying] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [volume, setVolume] = useState(100);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(7245); // Mock duration in seconds (2h 45s)
  const [showControls, setShowControls] = useState(true);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [quality, setQuality] = useState('1080p');
  const [showQualityMenu, setShowQualityMenu] = useState(false);

  useEffect(() => {
    let timer: NodeJS.Timeout;
    if (isPlaying && showControls) {
      timer = setTimeout(() => setShowControls(false), 3000);
    }
    return () => clearTimeout(timer);
  }, [isPlaying, showControls]);

  useEffect(() => {
    if (isPlaying) {
      const interval = setInterval(() => {
        setCurrentTime((prev) => Math.min(prev + 1, duration));
      }, 1000);
      return () => clearInterval(interval);
    }
  }, [isPlaying, duration]);

  const formatTime = (seconds: number) => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) {
      return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    }
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  const handleProgressClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const percentage = x / rect.width;
    setCurrentTime(percentage * duration);
  };

  const skip = (seconds: number) => {
    setCurrentTime((prev) => Math.max(0, Math.min(prev + seconds, duration)));
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 bg-black z-50 flex items-center justify-center"
      onMouseMove={() => setShowControls(true)}
    >
      {/* Video Content (Mock) */}
      <div className="relative w-full h-full flex items-center justify-center bg-black">
        <img
          src={media.backdrop}
          alt={media.title}
          className="w-full h-full object-contain"
        />
        
        {!isPlaying && (
          <motion.div
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            className="absolute inset-0 flex items-center justify-center"
          >
            <button
              onClick={() => setIsPlaying(true)}
              className="w-24 h-24 rounded-full bg-[#E50914] hover:bg-[#E50914]/90 flex items-center justify-center transition-all hover:scale-110"
            >
              <Play className="w-12 h-12 text-white fill-white ml-2" />
            </button>
          </motion.div>
        )}
      </div>

      {/* Controls Overlay */}
      <AnimatePresence>
        {showControls && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 bg-gradient-to-t from-black via-transparent to-black/50 flex flex-col"
          >
            {/* Top Bar */}
            <div className="flex items-center justify-between p-8">
              <div>
                <h2 className="text-white mb-1">{media.title}</h2>
                <p className="text-[#B3B3B3] text-sm">
                  {media.year} • {media.rating} • {media.type === 'movie' ? media.duration : `Season 1, Episode 1`}
                </p>
              </div>
              <button
                onClick={onClose}
                className="w-12 h-12 rounded-full bg-black/50 backdrop-blur-sm hover:bg-black/70 flex items-center justify-center transition-colors"
              >
                <X className="w-6 h-6 text-white" />
              </button>
            </div>

            {/* Center Controls (on hover) */}
            <div className="flex-1 flex items-center justify-center gap-8">
              <motion.button
                whileHover={{ scale: 1.1 }}
                whileTap={{ scale: 0.95 }}
                onClick={() => skip(-10)}
                className="w-16 h-16 rounded-full bg-black/50 backdrop-blur-sm hover:bg-black/70 flex items-center justify-center transition-colors"
              >
                <SkipBack className="w-8 h-8 text-white" />
              </motion.button>

              <motion.button
                whileHover={{ scale: 1.1 }}
                whileTap={{ scale: 0.95 }}
                onClick={() => setIsPlaying(!isPlaying)}
                className="w-20 h-20 rounded-full bg-white/10 backdrop-blur-sm hover:bg-white/20 flex items-center justify-center transition-colors border-2 border-white"
              >
                {isPlaying ? (
                  <Pause className="w-10 h-10 text-white" />
                ) : (
                  <Play className="w-10 h-10 text-white fill-white ml-1" />
                )}
              </motion.button>

              <motion.button
                whileHover={{ scale: 1.1 }}
                whileTap={{ scale: 0.95 }}
                onClick={() => skip(10)}
                className="w-16 h-16 rounded-full bg-black/50 backdrop-blur-sm hover:bg-black/70 flex items-center justify-center transition-colors"
              >
                <SkipForward className="w-8 h-8 text-white" />
              </motion.button>
            </div>

            {/* Bottom Controls */}
            <div className="p-8">
              {/* Progress Bar */}
              <div
                className="w-full h-2 bg-white/20 rounded-full mb-4 cursor-pointer group"
                onClick={handleProgressClick}
              >
                <div className="relative h-full">
                  <div
                    className="h-full bg-[#E50914] rounded-full transition-all"
                    style={{ width: `${(currentTime / duration) * 100}%` }}
                  />
                  <div
                    className="absolute top-1/2 -translate-y-1/2 w-4 h-4 bg-white rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
                    style={{ left: `${(currentTime / duration) * 100}%` }}
                  />
                </div>
              </div>

              {/* Control Buttons */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <button
                    onClick={() => setIsPlaying(!isPlaying)}
                    className="text-white hover:text-[#E50914] transition-colors"
                  >
                    {isPlaying ? <Pause className="w-6 h-6" /> : <Play className="w-6 h-6" />}
                  </button>

                  <button
                    onClick={() => skip(-10)}
                    className="text-white hover:text-[#E50914] transition-colors"
                  >
                    <SkipBack className="w-5 h-5" />
                  </button>

                  <button
                    onClick={() => skip(10)}
                    className="text-white hover:text-[#E50914] transition-colors"
                  >
                    <SkipForward className="w-5 h-5" />
                  </button>

                  {/* Volume */}
                  <div className="flex items-center gap-2 group/volume">
                    <button
                      onClick={() => setIsMuted(!isMuted)}
                      className="text-white hover:text-[#E50914] transition-colors"
                    >
                      {isMuted || volume === 0 ? (
                        <VolumeX className="w-6 h-6" />
                      ) : (
                        <Volume2 className="w-6 h-6" />
                      )}
                    </button>
                    <div className="w-0 group-hover/volume:w-24 overflow-hidden transition-all">
                      <input
                        type="range"
                        min="0"
                        max="100"
                        value={isMuted ? 0 : volume}
                        onChange={(e) => {
                          setVolume(Number(e.target.value));
                          setIsMuted(false);
                        }}
                        className="w-24 accent-[#E50914]"
                      />
                    </div>
                  </div>

                  <span className="text-white text-sm">
                    {formatTime(currentTime)} / {formatTime(duration)}
                  </span>
                </div>

                <div className="flex items-center gap-4">
                  <button className="text-white hover:text-[#E50914] transition-colors">
                    <Subtitles className="w-6 h-6" />
                  </button>

                  <button className="text-white hover:text-[#E50914] transition-colors">
                    <Cast className="w-6 h-6" />
                  </button>

                  <div className="relative">
                    <button
                      onClick={() => setShowQualityMenu(!showQualityMenu)}
                      className="text-white hover:text-[#E50914] transition-colors"
                    >
                      <Settings className="w-6 h-6" />
                    </button>
                    {showQualityMenu && (
                      <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="absolute bottom-full right-0 mb-2 bg-black/90 backdrop-blur-sm rounded-lg p-2 min-w-32"
                      >
                        {['4K', '1080p', '720p', 'Auto'].map((q) => (
                          <button
                            key={q}
                            onClick={() => {
                              setQuality(q);
                              setShowQualityMenu(false);
                            }}
                            className={`w-full text-left px-4 py-2 rounded hover:bg-white/10 transition-colors ${
                              quality === q ? 'text-[#E50914]' : 'text-white'
                            }`}
                          >
                            {q}
                          </button>
                        ))}
                      </motion.div>
                    )}
                  </div>

                  <button
                    onClick={() => setIsFullscreen(!isFullscreen)}
                    className="text-white hover:text-[#E50914] transition-colors"
                  >
                    {isFullscreen ? (
                      <Minimize className="w-6 h-6" />
                    ) : (
                      <Maximize className="w-6 h-6" />
                    )}
                  </button>
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Next Episode Preview (for series) */}
      {media.type === 'series' && currentTime > duration - 30 && (
        <motion.div
          initial={{ opacity: 0, x: 100 }}
          animate={{ opacity: 1, x: 0 }}
          className="absolute bottom-32 right-8 w-80 bg-black/90 backdrop-blur-sm rounded-lg overflow-hidden"
        >
          <div className="relative">
            <img
              src={media.thumbnail}
              alt="Next episode"
              className="w-full h-44 object-cover"
            />
            <div className="absolute inset-0 bg-gradient-to-t from-black to-transparent" />
            <div className="absolute bottom-0 left-0 right-0 p-4">
              <p className="text-[#B3B3B3] text-sm mb-1">Next Episode</p>
              <h3 className="text-white mb-2">Episode 2: Digital Divide</h3>
              <button className="w-full bg-white hover:bg-white/90 text-black py-2 rounded flex items-center justify-center gap-2 transition-colors">
                <Play className="w-4 h-4 fill-black" />
                <span>Play Now</span>
              </button>
            </div>
          </div>
        </motion.div>
      )}
    </motion.div>
  );
}

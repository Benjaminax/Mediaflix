import { motion } from 'motion/react';
import { Play, X, ChevronDown } from 'lucide-react';
import { MediaItem, Episode } from '../types';
import { useState } from 'react';

interface EpisodesViewProps {
  media: MediaItem;
  onClose: () => void;
  onPlayEpisode: (episode: Episode) => void;
}

export function EpisodesView({ media, onClose, onPlayEpisode }: EpisodesViewProps) {
  const [selectedSeason, setSelectedSeason] = useState(1);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 bg-[#141414] z-50 overflow-y-auto"
    >
      {/* Header */}
      <div className="sticky top-0 z-10 bg-[#141414]/95 backdrop-blur-sm border-b border-[#2a2a2a]">
        <div className="px-16 py-6 flex items-center justify-between">
          <div>
            <h1 className="text-white mb-2">{media.title}</h1>
            <p className="text-[#B3B3B3]">Episodes</p>
          </div>
          <button
            onClick={onClose}
            className="w-12 h-12 rounded-full bg-[#2a2a2a] hover:bg-[#3a3a3a] flex items-center justify-center transition-colors"
          >
            <X className="w-6 h-6 text-white" />
          </button>
        </div>
      </div>

      <div className="px-16 py-8">
        {/* Season Selector */}
        <div className="mb-8">
          <div className="relative inline-block">
            <select
              value={selectedSeason}
              onChange={(e) => setSelectedSeason(Number(e.target.value))}
              className="appearance-none bg-[#2a2a2a] text-white px-6 py-3 pr-12 rounded-lg cursor-pointer hover:bg-[#3a3a3a] transition-colors"
            >
              {Array.from({ length: media.seasons || 1 }, (_, i) => i + 1).map((season) => (
                <option key={season} value={season}>
                  Season {season}
                </option>
              ))}
            </select>
            <ChevronDown className="absolute right-4 top-1/2 -translate-y-1/2 w-5 h-5 text-white pointer-events-none" />
          </div>
        </div>

        {/* Episodes Grid */}
        <div className="grid grid-cols-1 gap-6 max-w-5xl">
          {media.episodes?.map((episode, index) => (
            <motion.div
              key={episode.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.1 }}
              className="group bg-[#181818] rounded-lg overflow-hidden hover:bg-[#2a2a2a] transition-all cursor-pointer"
              onClick={() => onPlayEpisode(episode)}
            >
              <div className="flex gap-6 p-4">
                {/* Episode Number */}
                <div className="flex-shrink-0 w-12 flex items-center justify-center text-[#B3B3B3]">
                  {episode.episodeNumber}
                </div>

                {/* Episode Thumbnail */}
                <div className="relative w-60 h-36 rounded overflow-hidden flex-shrink-0">
                  <img
                    src={episode.thumbnail}
                    alt={episode.title}
                    className="w-full h-full object-cover"
                  />
                  
                  {/* Play Button Overlay */}
                  <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                    <div className="w-14 h-14 rounded-full bg-white/20 backdrop-blur-sm flex items-center justify-center border-2 border-white group-hover:scale-110 transition-transform">
                      <Play className="w-6 h-6 text-white fill-white ml-1" />
                    </div>
                  </div>

                  {/* Progress Bar */}
                  {episode.progress && episode.progress > 0 && (
                    <div className="absolute bottom-0 left-0 right-0 h-1 bg-white/20">
                      <div
                        className="h-full bg-[#E50914]"
                        style={{ width: `${episode.progress}%` }}
                      />
                    </div>
                  )}
                </div>

                {/* Episode Info */}
                <div className="flex-1 min-w-0 flex flex-col justify-center">
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="text-white">{episode.title}</h3>
                    <span className="text-[#B3B3B3] text-sm flex-shrink-0 ml-4">
                      {episode.duration}
                    </span>
                  </div>
                  <p className="text-[#B3B3B3] line-clamp-2 mb-2">
                    {episode.description}
                  </p>
                  <p className="text-[#B3B3B3] text-sm">
                    Aired: {new Date(episode.airDate).toLocaleDateString('en-US', {
                      month: 'long',
                      day: 'numeric',
                      year: 'numeric'
                    })}
                  </p>
                </div>
              </div>
            </motion.div>
          ))}
        </div>

        {/* Empty State */}
        {(!media.episodes || media.episodes.length === 0) && (
          <div className="text-center py-16">
            <p className="text-[#B3B3B3]">No episodes available for this season.</p>
          </div>
        )}
      </div>
    </motion.div>
  );
}

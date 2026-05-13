import { motion } from 'motion/react';
import { Play, Plus, Share2, X, Clock, Star } from 'lucide-react';
import { MediaItem } from '../types';
import { Button } from './ui/button';

interface DetailPageProps {
  media: MediaItem;
  onClose: () => void;
  onPlay: () => void;
  onShowEpisodes?: () => void;
}

export function DetailPage({ media, onClose, onPlay, onShowEpisodes }: DetailPageProps) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 bg-[#141414] z-50 overflow-y-auto"
    >
      {/* Hero Section */}
      <div className="relative h-[90vh]">
        <img
          src={media.backdrop}
          alt={media.title}
          className="w-full h-full object-cover"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-[#141414] via-[#141414]/60 to-transparent" />
        <div className="absolute inset-0 bg-gradient-to-r from-[#141414] via-transparent to-transparent" />

        {/* Close Button */}
        <button
          onClick={onClose}
          className="absolute top-8 right-8 w-12 h-12 rounded-full bg-black/50 backdrop-blur-sm hover:bg-black/70 flex items-center justify-center transition-colors z-10"
        >
          <X className="w-6 h-6 text-white" />
        </button>

        {/* Content */}
        <div className="absolute bottom-0 left-0 right-0 p-16">
          <div className="max-w-4xl">
            <motion.h1
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 }}
              className="text-white mb-6"
            >
              {media.title}
            </motion.h1>

            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.3 }}
              className="flex items-center gap-4 mb-6 text-white"
            >
              <div className="flex items-center gap-2">
                <Star className="w-5 h-5 fill-[#FFB000] text-[#FFB000]" />
                <span>8.5/10</span>
              </div>
              <span className="text-[#46D369]">{media.rating}</span>
              <span>{media.year}</span>
              <span>{media.type === 'movie' ? media.duration : `${media.seasons} Seasons`}</span>
            </motion.div>

            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.4 }}
              className="flex gap-3 mb-6"
            >
              {media.genre.map((genre) => (
                <span
                  key={genre}
                  className="px-4 py-2 bg-white/10 backdrop-blur-sm rounded-lg text-white"
                >
                  {genre}
                </span>
              ))}
            </motion.div>

            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.5 }}
              className="text-white/90 mb-8 max-w-3xl leading-relaxed"
            >
              {media.description}
            </motion.p>

            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.6 }}
              className="flex gap-4"
            >
              <Button
                onClick={onPlay}
                className="bg-[#E50914] hover:bg-[#E50914]/90 text-white px-8 py-6 rounded-lg flex items-center gap-3 transition-all hover:scale-105"
              >
                <Play className="w-6 h-6 fill-white" />
                {media.progress ? `Resume • ${media.progress}%` : 'Play'}
              </Button>
              {media.type === 'series' && onShowEpisodes && (
                <Button
                  onClick={onShowEpisodes}
                  variant="secondary"
                  className="bg-white/20 hover:bg-white/30 backdrop-blur-md text-white px-8 py-6 rounded-lg flex items-center gap-3 transition-all hover:scale-105"
                >
                  <Clock className="w-6 h-6" />
                  Episodes
                </Button>
              )}
              <Button
                variant="secondary"
                className="bg-white/20 hover:bg-white/30 backdrop-blur-md text-white px-8 py-6 rounded-lg flex items-center gap-3 transition-all hover:scale-105"
              >
                <Plus className="w-6 h-6" />
                My List
              </Button>
              <Button
                variant="secondary"
                className="bg-white/20 hover:bg-white/30 backdrop-blur-md text-white px-8 py-6 rounded-lg flex items-center gap-3 transition-all hover:scale-105"
              >
                <Share2 className="w-6 h-6" />
                Share
              </Button>
            </motion.div>
          </div>
        </div>
      </div>

      {/* Details Section */}
      <div className="px-16 py-12 bg-[#141414]">
        <div className="max-w-7xl">
          <div className="grid grid-cols-2 gap-12">
            {/* Left Column */}
            <div>
              <h3 className="text-white mb-6">Cast</h3>
              <div className="text-[#B3B3B3] space-y-2">
                {media.cast.map((actor) => (
                  <div key={actor} className="py-2">
                    {actor}
                  </div>
                ))}
              </div>
            </div>

            {/* Right Column */}
            <div>
              <h3 className="text-white mb-6">Details</h3>
              <div className="space-y-4 text-[#B3B3B3]">
                <div>
                  <span className="text-white">Director:</span> {media.director}
                </div>
                <div>
                  <span className="text-white">Genres:</span> {media.genre.join(', ')}
                </div>
                <div>
                  <span className="text-white">Released:</span> {media.year}
                </div>
                <div>
                  <span className="text-white">Rating:</span> {media.rating}
                </div>
              </div>
            </div>
          </div>

          {/* Similar Content */}
          <div className="mt-16">
            <h3 className="text-white mb-6">More Like This</h3>
            <div className="grid grid-cols-3 gap-4">
              {[1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="relative aspect-video rounded-lg overflow-hidden bg-[#2a2a2a] hover:scale-105 transition-transform cursor-pointer"
                >
                  <img
                    src={media.thumbnail}
                    alt="Similar content"
                    className="w-full h-full object-cover"
                  />
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
}

import { motion } from 'motion/react';
import { Play, Info, Plus } from 'lucide-react';
import { MediaItem } from '../types';
import { useState } from 'react';

interface MovieCardProps {
  media: MediaItem;
  onPlay: () => void;
  onInfo: () => void;
}

export function MovieCard({ media, onPlay, onInfo }: MovieCardProps) {
  const [isHovered, setIsHovered] = useState(false);

  return (
    <motion.div
      className="relative group cursor-pointer flex-shrink-0"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      whileHover={{ scale: 1.05, zIndex: 10 }}
      transition={{ duration: 0.3 }}
    >
      {/* Thumbnail */}
      <div className="relative w-72 h-40 rounded-lg overflow-hidden">
        <img
          src={media.thumbnail}
          alt={media.title}
          className="w-full h-full object-cover"
        />
        
        {/* Progress Bar */}
        {media.progress && media.progress > 0 && (
          <div className="absolute bottom-0 left-0 right-0 h-1 bg-white/20">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${media.progress}%` }}
              className="h-full bg-[#E50914]"
            />
          </div>
        )}

        {/* Hover Overlay */}
        {isHovered && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="absolute inset-0 bg-gradient-to-t from-black via-black/60 to-transparent flex flex-col justify-end p-4"
          >
            <h3 className="text-white mb-2">{media.title}</h3>
            <div className="flex items-center gap-2 text-sm text-white/80 mb-3">
              <span className="text-[#46D369]">{media.rating}</span>
              <span>•</span>
              <span>{media.year}</span>
              <span>•</span>
              <span>{media.type === 'movie' ? media.duration : `${media.seasons} Seasons`}</span>
            </div>
            <div className="flex gap-2">
              <motion.button
                whileHover={{ scale: 1.1 }}
                whileTap={{ scale: 0.95 }}
                onClick={(e) => {
                  e.stopPropagation();
                  onPlay();
                }}
                className="w-8 h-8 rounded-full bg-white flex items-center justify-center hover:bg-white/90 transition-colors"
              >
                <Play className="w-4 h-4 text-black fill-black" />
              </motion.button>
              <motion.button
                whileHover={{ scale: 1.1 }}
                whileTap={{ scale: 0.95 }}
                onClick={(e) => {
                  e.stopPropagation();
                  onInfo();
                }}
                className="w-8 h-8 rounded-full bg-white/20 backdrop-blur-sm flex items-center justify-center hover:bg-white/30 transition-colors"
              >
                <Info className="w-4 h-4 text-white" />
              </motion.button>
              <motion.button
                whileHover={{ scale: 1.1 }}
                whileTap={{ scale: 0.95 }}
                className="w-8 h-8 rounded-full bg-white/20 backdrop-blur-sm flex items-center justify-center hover:bg-white/30 transition-colors"
              >
                <Plus className="w-4 h-4 text-white" />
              </motion.button>
            </div>
          </motion.div>
        )}
      </div>
    </motion.div>
  );
}

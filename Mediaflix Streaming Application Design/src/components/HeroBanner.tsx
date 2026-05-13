import { Play, Info } from 'lucide-react';
import { motion } from 'motion/react';
import { MediaItem } from '../types';
import { Button } from './ui/button';

interface HeroBannerProps {
  media: MediaItem;
  onPlay: () => void;
  onInfo: () => void;
}

export function HeroBanner({ media, onPlay, onInfo }: HeroBannerProps) {
  return (
    <div className="relative h-[85vh] w-full overflow-hidden">
      {/* Background Image */}
      <div className="absolute inset-0">
        <img
          src={media.backdrop}
          alt={media.title}
          className="w-full h-full object-cover"
        />
        {/* Gradient Overlays */}
        <div className="absolute inset-0 bg-gradient-to-t from-[#141414] via-[#141414]/40 to-transparent" />
        <div className="absolute inset-0 bg-gradient-to-r from-[#141414] via-transparent to-transparent" />
      </div>

      {/* Content */}
      <motion.div
        initial={{ opacity: 0, y: 50 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, delay: 0.2 }}
        className="relative h-full flex flex-col justify-end pb-32 px-16 max-w-3xl"
      >
        {/* Title */}
        <motion.h1
          initial={{ opacity: 0, x: -50 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.8, delay: 0.4 }}
          className="text-white mb-4"
        >
          {media.title}
        </motion.h1>

        {/* Meta Information */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.8, delay: 0.5 }}
          className="flex items-center gap-4 mb-6 text-white"
        >
          <span className="text-[#46D369]">{media.rating}</span>
          <span>{media.year}</span>
          <span>{media.type === 'movie' ? media.duration : `${media.seasons} Seasons`}</span>
          <div className="flex gap-2">
            {media.genre.slice(0, 3).map((genre) => (
              <span key={genre} className="px-3 py-1 bg-white/10 backdrop-blur-sm rounded text-sm">
                {genre}
              </span>
            ))}
          </div>
        </motion.div>

        {/* Description */}
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.8, delay: 0.6 }}
          className="text-white/90 mb-8 max-w-2xl leading-relaxed"
        >
          {media.description}
        </motion.p>

        {/* Action Buttons */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.7 }}
          className="flex gap-4"
        >
          <Button
            onClick={onPlay}
            className="bg-[#E50914] hover:bg-[#E50914]/90 text-white px-8 py-6 rounded-lg flex items-center gap-3 transition-all hover:scale-105"
          >
            <Play className="w-6 h-6 fill-white" />
            <span>Play</span>
          </Button>
          <Button
            onClick={onInfo}
            variant="secondary"
            className="bg-white/20 hover:bg-white/30 backdrop-blur-md text-white px-8 py-6 rounded-lg flex items-center gap-3 transition-all hover:scale-105"
          >
            <Info className="w-6 h-6" />
            <span>More Info</span>
          </Button>
        </motion.div>
      </motion.div>
    </div>
  );
}

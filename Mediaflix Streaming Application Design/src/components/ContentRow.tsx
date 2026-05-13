import { ChevronLeft, ChevronRight } from 'lucide-react';
import { motion } from 'motion/react';
import { useRef, useState } from 'react';
import { MediaItem } from '../types';
import { MovieCard } from './MovieCard';

interface ContentRowProps {
  title: string;
  items: MediaItem[];
  onPlay: (media: MediaItem) => void;
  onInfo: (media: MediaItem) => void;
}

export function ContentRow({ title, items, onPlay, onInfo }: ContentRowProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [showLeftArrow, setShowLeftArrow] = useState(false);
  const [showRightArrow, setShowRightArrow] = useState(true);

  const scroll = (direction: 'left' | 'right') => {
    if (scrollRef.current) {
      const scrollAmount = scrollRef.current.clientWidth * 0.8;
      const newScrollLeft =
        scrollRef.current.scrollLeft + (direction === 'left' ? -scrollAmount : scrollAmount);
      
      scrollRef.current.scrollTo({
        left: newScrollLeft,
        behavior: 'smooth',
      });

      setTimeout(() => {
        if (scrollRef.current) {
          setShowLeftArrow(scrollRef.current.scrollLeft > 0);
          setShowRightArrow(
            scrollRef.current.scrollLeft <
              scrollRef.current.scrollWidth - scrollRef.current.clientWidth - 10
          );
        }
      }, 300);
    }
  };

  return (
    <div className="mb-12 group/row">
      <h2 className="text-white mb-4 px-16">{title}</h2>
      
      <div className="relative">
        {/* Left Arrow */}
        {showLeftArrow && (
          <motion.button
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => scroll('left')}
            className="absolute left-4 top-1/2 -translate-y-1/2 z-20 w-12 h-32 bg-black/80 flex items-center justify-center opacity-0 group-hover/row:opacity-100 transition-opacity hover:bg-black/90"
          >
            <ChevronLeft className="w-8 h-8 text-white" />
          </motion.button>
        )}

        {/* Right Arrow */}
        {showRightArrow && (
          <motion.button
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => scroll('right')}
            className="absolute right-4 top-1/2 -translate-y-1/2 z-20 w-12 h-32 bg-black/80 flex items-center justify-center opacity-0 group-hover/row:opacity-100 transition-opacity hover:bg-black/90"
          >
            <ChevronRight className="w-8 h-8 text-white" />
          </motion.button>
        )}

        {/* Scrollable Content */}
        <div
          ref={scrollRef}
          className="flex gap-4 overflow-x-auto scrollbar-hide px-16 py-2"
          style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}
        >
          {items.map((item) => (
            <MovieCard
              key={item.id}
              media={item}
              onPlay={() => onPlay(item)}
              onInfo={() => onInfo(item)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

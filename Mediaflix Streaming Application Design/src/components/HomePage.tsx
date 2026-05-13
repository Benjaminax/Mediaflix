import { motion } from 'motion/react';
import { MediaItem } from '../types';
import { HeroBanner } from './HeroBanner';
import { ContentRow } from './ContentRow';

interface HomePageProps {
  items: MediaItem[];
  onPlay: (media: MediaItem) => void;
  onInfo: (media: MediaItem) => void;
}

export function HomePage({ items, onPlay, onInfo }: HomePageProps) {
  const featuredItem = items[0];
  
  const recentlyWatched = items.filter((item) => item.progress && item.progress > 0);
  const movies = items.filter((item) => item.type === 'movie');
  const series = items.filter((item) => item.type === 'series');
  const recentlyAdded = items.slice(0, 6);
  
  const actionMovies = items.filter((item) => item.genre.includes('Action'));
  const sciFiContent = items.filter((item) => item.genre.includes('Sci-Fi'));
  const dramaContent = items.filter((item) => item.genre.includes('Drama'));
  const comedyContent = items.filter((item) => item.genre.includes('Comedy'));

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="min-h-screen bg-[#141414]"
    >
      {/* Hero Banner */}
      <HeroBanner
        media={featuredItem}
        onPlay={() => onPlay(featuredItem)}
        onInfo={() => onInfo(featuredItem)}
      />

      {/* Content Rows */}
      <div className="-mt-32 relative z-10 pb-16">
        {recentlyWatched.length > 0 && (
          <ContentRow
            title="Continue Watching"
            items={recentlyWatched}
            onPlay={onPlay}
            onInfo={onInfo}
          />
        )}
        
        <ContentRow
          title="Recently Added"
          items={recentlyAdded}
          onPlay={onPlay}
          onInfo={onInfo}
        />

        <ContentRow
          title="Popular Movies"
          items={movies}
          onPlay={onPlay}
          onInfo={onInfo}
        />

        {actionMovies.length > 0 && (
          <ContentRow
            title="Action & Adventure"
            items={actionMovies}
            onPlay={onPlay}
            onInfo={onInfo}
          />
        )}

        <ContentRow
          title="TV Series"
          items={series}
          onPlay={onPlay}
          onInfo={onInfo}
        />

        {sciFiContent.length > 0 && (
          <ContentRow
            title="Sci-Fi & Fantasy"
            items={sciFiContent}
            onPlay={onPlay}
            onInfo={onInfo}
          />
        )}

        {dramaContent.length > 0 && (
          <ContentRow
            title="Drama"
            items={dramaContent}
            onPlay={onPlay}
            onInfo={onInfo}
          />
        )}

        {comedyContent.length > 0 && (
          <ContentRow
            title="Comedy"
            items={comedyContent}
            onPlay={onPlay}
            onInfo={onInfo}
          />
        )}
      </div>
    </motion.div>
  );
}

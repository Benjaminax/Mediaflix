import { motion } from 'motion/react';
import { Search, SlidersHorizontal, Grid3x3, List } from 'lucide-react';
import { useState } from 'react';
import { MediaItem } from '../types';
import { MovieCard } from './MovieCard';

interface SearchPageProps {
  items: MediaItem[];
  onPlay: (media: MediaItem) => void;
  onInfo: (media: MediaItem) => void;
}

export function SearchPage({ items, onPlay, onInfo }: SearchPageProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [showFilters, setShowFilters] = useState(false);
  const [selectedGenre, setSelectedGenre] = useState<string>('all');
  const [selectedType, setSelectedType] = useState<string>('all');

  const allGenres = Array.from(
    new Set(items.flatMap((item) => item.genre))
  ).sort();

  const filteredItems = items.filter((item) => {
    const matchesSearch = item.title.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesGenre = selectedGenre === 'all' || item.genre.includes(selectedGenre);
    const matchesType = selectedType === 'all' || item.type === selectedType;
    return matchesSearch && matchesGenre && matchesType;
  });

  return (
    <div className="min-h-screen bg-[#141414] pt-20 px-16 pb-16">
      {/* Search Header */}
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-12"
      >
        <h1 className="text-white mb-8">Search</h1>

        {/* Search Bar */}
        <div className="flex gap-4 mb-6">
          <div className="flex-1 relative">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-[#B3B3B3]" />
            <input
              type="text"
              placeholder="Search movies, series..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-[#2a2a2a] text-white pl-12 pr-4 py-4 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#E50914]"
            />
          </div>
          <button
            onClick={() => setShowFilters(!showFilters)}
            className={`px-6 py-4 rounded-lg flex items-center gap-2 transition-colors ${
              showFilters ? 'bg-[#E50914] text-white' : 'bg-[#2a2a2a] text-white hover:bg-[#3a3a3a]'
            }`}
          >
            <SlidersHorizontal className="w-5 h-5" />
            Filters
          </button>
          <div className="flex gap-2 bg-[#2a2a2a] rounded-lg p-1">
            <button
              onClick={() => setViewMode('grid')}
              className={`p-3 rounded ${
                viewMode === 'grid' ? 'bg-[#E50914] text-white' : 'text-[#B3B3B3] hover:text-white'
              }`}
            >
              <Grid3x3 className="w-5 h-5" />
            </button>
            <button
              onClick={() => setViewMode('list')}
              className={`p-3 rounded ${
                viewMode === 'list' ? 'bg-[#E50914] text-white' : 'text-[#B3B3B3] hover:text-white'
              }`}
            >
              <List className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Filters */}
        {showFilters && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="bg-[#181818] rounded-lg p-6 mb-6"
          >
            <div className="grid grid-cols-2 gap-6">
              <div>
                <label className="text-white mb-3 block">Type</label>
                <div className="flex gap-2">
                  <button
                    onClick={() => setSelectedType('all')}
                    className={`px-4 py-2 rounded-lg transition-colors ${
                      selectedType === 'all'
                        ? 'bg-[#E50914] text-white'
                        : 'bg-[#2a2a2a] text-[#B3B3B3] hover:text-white'
                    }`}
                  >
                    All
                  </button>
                  <button
                    onClick={() => setSelectedType('movie')}
                    className={`px-4 py-2 rounded-lg transition-colors ${
                      selectedType === 'movie'
                        ? 'bg-[#E50914] text-white'
                        : 'bg-[#2a2a2a] text-[#B3B3B3] hover:text-white'
                    }`}
                  >
                    Movies
                  </button>
                  <button
                    onClick={() => setSelectedType('series')}
                    className={`px-4 py-2 rounded-lg transition-colors ${
                      selectedType === 'series'
                        ? 'bg-[#E50914] text-white'
                        : 'bg-[#2a2a2a] text-[#B3B3B3] hover:text-white'
                    }`}
                  >
                    Series
                  </button>
                </div>
              </div>

              <div>
                <label className="text-white mb-3 block">Genre</label>
                <select
                  value={selectedGenre}
                  onChange={(e) => setSelectedGenre(e.target.value)}
                  className="w-full bg-[#2a2a2a] text-white px-4 py-2 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#E50914]"
                >
                  <option value="all">All Genres</option>
                  {allGenres.map((genre) => (
                    <option key={genre} value={genre}>
                      {genre}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </motion.div>
        )}

        {/* Results Count */}
        <p className="text-[#B3B3B3]">
          {filteredItems.length} {filteredItems.length === 1 ? 'result' : 'results'}
          {searchQuery && ` for "${searchQuery}"`}
        </p>
      </motion.div>

      {/* Results Grid */}
      {viewMode === 'grid' ? (
        <div className="grid grid-cols-4 gap-4">
          {filteredItems.map((item, index) => (
            <motion.div
              key={item.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.05 }}
            >
              <MovieCard media={item} onPlay={() => onPlay(item)} onInfo={() => onInfo(item)} />
            </motion.div>
          ))}
        </div>
      ) : (
        <div className="space-y-4">
          {filteredItems.map((item, index) => (
            <motion.div
              key={item.id}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: index * 0.05 }}
              className="bg-[#181818] rounded-lg overflow-hidden hover:bg-[#2a2a2a] transition-colors cursor-pointer"
              onClick={() => onInfo(item)}
            >
              <div className="flex gap-6 p-4">
                <img
                  src={item.thumbnail}
                  alt={item.title}
                  className="w-60 h-36 object-cover rounded"
                />
                <div className="flex-1 flex flex-col justify-center">
                  <h3 className="text-white mb-2">{item.title}</h3>
                  <div className="flex items-center gap-3 mb-3 text-[#B3B3B3] text-sm">
                    <span className="text-[#46D369]">{item.rating}</span>
                    <span>•</span>
                    <span>{item.year}</span>
                    <span>•</span>
                    <span>{item.type === 'movie' ? item.duration : `${item.seasons} Seasons`}</span>
                    <span>•</span>
                    <span>{item.genre.join(', ')}</span>
                  </div>
                  <p className="text-[#B3B3B3] text-sm line-clamp-2">{item.description}</p>
                </div>
              </div>
            </motion.div>
          ))}
        </div>
      )}

      {/* Empty State */}
      {filteredItems.length === 0 && (
        <div className="text-center py-20">
          <Search className="w-16 h-16 text-[#B3B3B3] mx-auto mb-4" />
          <h3 className="text-white mb-2">No results found</h3>
          <p className="text-[#B3B3B3]">Try adjusting your search or filters</p>
        </div>
      )}
    </div>
  );
}

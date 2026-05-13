export interface MediaItem {
  id: string;
  title: string;
  type: 'movie' | 'series';
  thumbnail: string;
  backdrop: string;
  year: number;
  rating: string;
  duration?: string;
  seasons?: number;
  description: string;
  genre: string[];
  cast: string[];
  director: string;
  progress?: number;
  episodes?: Episode[];
}

export interface Episode {
  id: string;
  episodeNumber: number;
  seasonNumber: number;
  title: string;
  thumbnail: string;
  duration: string;
  description: string;
  airDate: string;
  progress?: number;
}

export type ViewType = 'home' | 'movies' | 'series' | 'search' | 'settings' | 'detail' | 'player';

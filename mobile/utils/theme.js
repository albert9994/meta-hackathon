/** VibeRide shared palette. The accent matches the route glow polyline (#fc5200). */
export const colors = {
  bg: '#0f1a17',
  card: '#18261f',
  cardAlt: '#1f3028',
  border: '#2c4339',
  text: '#f3f7f4',
  muted: '#8da399',
  accent: '#fc5200',
  calm: '#4cc38a',
  warn: '#f5b942',
  danger: '#ef5350',
  overlay: 'rgba(5, 12, 10, 0.72)',
};

export const radius = { sm: 8, md: 14, lg: 22 };

/** "tram_tracks" -> "tram tracks" */
export const humanize = (value) => (value ? String(value).replace(/_/g, ' ') : '');

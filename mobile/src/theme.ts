// Forest Floor palette. Every color in the app comes from here.
export const color = {
  spruce: '#1E3B32',
  spruceSoft: '#2C4F43',
  moss: '#5E7D5A',
  mossTint: '#E3E9E1',
  bark: '#4A3D33',
  paper: '#F5F2EC',
  card: '#FFFFFF',
  ink: '#16201C',
  inkSoft: '#5C655F', // secondary text (Lichen darkened to pass 4.5:1 on paper)
  lichen: '#8A938C', // hairline icons, disabled
  line: '#E4DFD5',
  lineStrong: '#D9D2C4',
  lineSoft: '#EFEBE3',
  well: '#EAE5DB',
  nightCard: '#22302A',
  nightText: '#A9B5AE',
  nightLine: '#3A4A43',
  live: '#8FB08A', // Moss lifted for dark backgrounds
} as const;

export const status = {
  healthy: { label: 'Healthy', dot: '#5E7D5A', tint: '#E3E9E1', text: '#3F5A3C' },
  watch: { label: 'Watch', dot: '#C08A2E', tint: '#F3E7CF', text: '#7A5414' },
  infested: { label: 'Infested', dot: '#A3442F', tint: '#F4DED7', text: '#8A3524' },
  unrated: { label: 'Not rated', dot: '#8A938C', tint: '#EAE5DB', text: '#5C655F' }, // server visits with no health check
} as const;
export type Status = keyof typeof status;

// 8-point grid.
export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const;
export const radius = { sm: 12, md: 16, lg: 20, pill: 999 } as const;

export const font = {
  regular: 'Geist_400Regular',
  medium: 'Geist_500Medium',
  semibold: 'Geist_600SemiBold',
  display: 'Fraunces_500Medium',
} as const;

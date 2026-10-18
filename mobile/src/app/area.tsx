import { useLocalSearchParams } from 'expo-router';
import type { Bbox } from '@/api';
import Insights from '@/Insights';

// Analysis of one saved section (?section=id) or of the area framed on the map (?bbox=w,s,e,n).
export default function Area() {
  const { section, bbox } = useLocalSearchParams<{ section?: string; bbox?: string }>();
  if (section) return <Insights scope={{ kind: 'section', id: Number(section) }} />;
  return <Insights scope={{ kind: 'area', bbox: (bbox ?? '').split(',').map(Number) as Bbox }} />;
}

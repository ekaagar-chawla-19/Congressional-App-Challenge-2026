import type { TreeRow } from './data';

export type Match = { tree: TreeRow; score: number };

// Cosine similarity a match must clear; below it the photos are treated as a new tree.
// Set this from the threshold chosen on validation trees.
export const MATCH_THRESHOLD = 0.6;

// Placeholder for the HemlockID model (DINOv2 embedding vs. each tree's scan history).
// Gives a stable pseudo-random ranking so the flow can be exercised end to end.
export async function identify(photos: string[], trees: TreeRow[]): Promise<Match[]> {
  await new Promise((r) => setTimeout(r, 900));
  const seed = photos.join('');
  const score = (id: string) => {
    let h = 0;
    for (const ch of seed + id) h = (h * 31 + ch.charCodeAt(0)) | 0;
    return 0.3 + ((h >>> 0) % 66) / 100; // 0.30 to 0.95
  };
  return trees
    .map((tree) => ({ tree, score: score(tree.id) }))
    .sort((a, b) => b.score - a.score)
    .slice(0, 3);
}

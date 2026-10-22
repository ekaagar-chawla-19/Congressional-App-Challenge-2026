// The species the bark model knows (species/labels.py), with the tree ID prefix each one gets on the phone.
// HemlockID is built for Eastern hemlock: hemlocks get the full diagnosis (adelgid, scale, drought). Other species
// are tracked too in phone-only mode (their own ID, history, sensor readings and drought stress), and matching them
// again on a later visit is experimental: the fingerprint model was trained on hemlock bark.

export const HEMLOCK = 'tsuga_canadensis';
export const UNKNOWN = 'unknown';

export const SPECIES: Record<string, { name: string; prefix: string }> = {
  tsuga_canadensis: { name: 'Eastern hemlock', prefix: 'H' },
  pinus_strobus: { name: 'Eastern white pine', prefix: 'WP' },
  pinus_resinosa: { name: 'Red pine', prefix: 'RP' },
  pinus_rigida: { name: 'Pitch pine', prefix: 'PP' },
  fagus_grandifolia: { name: 'American beech', prefix: 'AB' },
  acer_rubrum: { name: 'Red maple', prefix: 'RM' },
  acer_platanoides: { name: 'Norway maple', prefix: 'NM' },
  populus_grandidentata: { name: 'Bigtooth aspen', prefix: 'BA' },
  [UNKNOWN]: { name: 'Unidentified species', prefix: 'T' },
};

export const speciesName = (label: string | null | undefined) => SPECIES[label ?? HEMLOCK]?.name ?? label ?? 'Eastern hemlock';
export const idPrefix = (label: string | null | undefined) => SPECIES[label ?? HEMLOCK]?.prefix ?? 'T';
export const isHemlock = (label: string | null | undefined) => (label ?? HEMLOCK) === HEMLOCK;
/** Conditions that only attack hemlocks: never assessed for other species. */
export const HEMLOCK_ONLY = ['hwa', 'ehs'];

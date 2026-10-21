import { useState } from 'react';
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import type { ModelChoice, ModelKey } from './api';
import { CircleCheck, ShieldCheck, Sparkles, Timer, TriangleAlert, type LucideIcon } from './icons';
import { recommended, speedLabel } from './models';
import { color, font, radius, space } from './theme';
import { Button, Clamp, T } from './ui';

const Small = ({ as: Glyph, c }: { as: LucideIcon; c: string }) => <Glyph size={14} strokeWidth={1.75} color={c} />;

// A bottom sheet that asks which model to scan with, like the model menu in ChatGPT or Claude: one row per
// model with what it is good at, the measured accuracy on real photos, speed, and whether it checks species.
export function ModelPicker({ visible, models, value, error, photos = 0, first, onChoose, onCancel }: {
  visible: boolean;
  models: ModelChoice[] | null;
  value: ModelKey | null;
  error?: string | null;
  photos?: number; // photos already taken: switching models starts the scan again
  first?: boolean; // opened before the scan: Cancel leaves the camera
  onChoose(key: ModelKey | null): void; // null: the models could not be listed, use the server's default
  onCancel(): void;
}) {
  const insets = useSafeAreaInsets();
  // The row tapped in this opening of the sheet; until then the current model is selected.
  const [tapped, setTapped] = useState<ModelKey | null>(null);
  const pick = tapped ?? value;
  const close = (f: () => void) => () => (setTapped(null), f());
  const best = models ? recommended(models) : null;
  const chosen = models?.find((m) => m.key === pick) ?? null;
  const restart = photos > 0 && pick !== value;

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={close(onCancel)}>
      <View style={s.backdrop}>
        <Pressable style={StyleSheet.absoluteFill} onPress={close(onCancel)} accessibilityLabel="Close model picker" />
        <View style={[s.sheet, { paddingBottom: Math.max(insets.bottom, space.lg) }]} accessibilityViewIsModal>
          <View style={s.grabber} />
          <View style={{ gap: 2 }}>
            <T v="title">Choose a model</T>
            <T v="caption">Both run on the HemlockID server and compare the bark with every tree in this forest.</T>
          </View>

          {!models ? (
            <View style={s.state}>
              {error ? (
                <>
                  <T v="caption" c={color.inkSoft} style={{ textAlign: 'center' }}>{`Could not load the models: ${error}`}</T>
                  <T v="caption" style={{ textAlign: 'center' }}>{"The scan will use the server's default model."}</T>
                </>
              ) : <ActivityIndicator color={color.spruce} />}
            </View>
          ) : (
            <ScrollView style={{ flexGrow: 0 }} contentContainerStyle={{ gap: space.sm }}>
              {models.map((m) => {
                const on = m.key === pick;
                return (
                  <Pressable
                    key={m.key}
                    onPress={() => setTapped(m.key)}
                    accessibilityRole="radio"
                    accessibilityState={{ selected: on }}
                    accessibilityLabel={`${m.name}. ${m.tagline}`}
                    style={({ pressed }) => [s.option, on && s.optionOn, pressed && { opacity: 0.85 }]}>
                    <View style={{ flex: 1, gap: 4 }}>
                      <View style={s.nameRow}>
                        <T v="label">{m.name}</T>
                        {m.key === best && !m.demo && (
                          <View style={s.pill}>
                            <Small as={Sparkles} c={color.spruce} />
                            <T v="caption" c={color.spruce} style={s.pillText}>Recommended</T>
                          </View>
                        )}
                      </View>
                      <T v="caption" c={color.ink}>{m.tagline}</T>
                      <View style={s.meta}>
                        {m.real_photo_top1 != null && (
                          <T v="caption" style={s.metaText}>{`Right tree first on ${Math.round(m.real_photo_top1 * 100)}% of real photos`}</T>
                        )}
                        <View style={s.metaItem}>
                          <Small as={m.checks_species ? ShieldCheck : TriangleAlert} c={m.checks_species ? color.moss : '#C08A2E'} />
                          <T v="caption" style={s.metaText}>{m.checks_species ? 'Checks the species' : 'No species check'}</T>
                        </View>
                        {speedLabel(m) && (
                          <View style={s.metaItem}>
                            <Small as={Timer} c={color.lichen} />
                            <T v="caption" style={s.metaText}>{speedLabel(m)}</T>
                          </View>
                        )}
                      </View>
                    </View>
                    <View style={[s.radio, on && s.radioOn]}>{on && <CircleCheck size={22} strokeWidth={2} color={color.spruce} />}</View>
                  </Pressable>
                );
              })}
              {chosen && <Clamp v="caption" lines={2} style={{ fontSize: 12, lineHeight: 17 }}>{chosen.description}</Clamp>}
            </ScrollView>
          )}

          {restart && (
            <T v="caption" c="#7A5414">{`Switching to ${chosen?.name} starts this scan again (${photos} photo${photos === 1 ? '' : 's'} taken).`}</T>
          )}
          <Button
            title={models ? (chosen ? `Scan with ${chosen.name}` : 'Choose a model') : 'Continue'}
            disabled={!!models && !chosen}
            onPress={close(() => (models ? pick && onChoose(pick) : onChoose(null)))}
          />
          {first && <Button title="Cancel" secondary onPress={close(onCancel)} />}
        </View>
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  backdrop: { flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(22, 32, 28, 0.55)' },
  sheet: { gap: space.md, paddingTop: space.sm, paddingHorizontal: space.lg, borderTopLeftRadius: 24, borderTopRightRadius: 24, backgroundColor: color.paper, maxHeight: '88%', width: '100%', maxWidth: 560, alignSelf: 'center' },
  grabber: { alignSelf: 'center', width: 40, height: 4, borderRadius: 2, backgroundColor: color.lineStrong, marginBottom: space.xs },
  state: { minHeight: 120, alignItems: 'center', justifyContent: 'center', gap: space.sm },
  option: { flexDirection: 'row', alignItems: 'center', gap: space.md, padding: space.md, borderRadius: radius.md, borderWidth: 1.5, borderColor: color.line, backgroundColor: color.card },
  optionOn: { borderColor: color.spruce, backgroundColor: '#F7FAF6' },
  nameRow: { flexDirection: 'row', alignItems: 'center', gap: space.sm, flexWrap: 'wrap' },
  pill: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 8, height: 22, borderRadius: radius.pill, backgroundColor: color.mossTint },
  pillText: { fontSize: 11, fontFamily: font.semibold },
  meta: { gap: 3, marginTop: 2 },
  metaItem: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  metaText: { fontSize: 12, lineHeight: 16 },
  radio: { width: 24, height: 24, borderRadius: 12, borderWidth: 1.5, borderColor: color.lineStrong, alignItems: 'center', justifyContent: 'center' },
  radioOn: { borderWidth: 0 },
});

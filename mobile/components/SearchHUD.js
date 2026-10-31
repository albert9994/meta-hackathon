import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Keyboard,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { planRoute } from '../utils/api';
import { colors, radius } from '../utils/theme';

/** One-tap vibes. `id` is sent to the backend as `vibe_preset`. */
export const VIBE_PRESETS = [
  { id: 'green_shady', label: 'Green & Shady', emoji: '🌿', placeholder: 'e.g. From UPB Regie to Carol Park through tree-lined streets' },
  { id: 'historic_chill', label: 'Historic & Chill', emoji: '🏛️', placeholder: 'e.g. From Cotroceni to Old Town past historic facades' },
  { id: 'pitstop', label: 'Pitstop Edition', emoji: '☕', placeholder: 'e.g. To Cișmigiu Park with a specialty coffee stop' },
];

const MIN_PROMPT = 3;
const MAX_PROMPT = 300;

/**
 * Natural-language route search with vibe presets.
 *
 * Props
 *   city              string   default "Bucharest" (sent to the planner)
 *   onSearchStart()   called when a request begins
 *   onRoutePlanned(data, { prompt, vibePreset })   data = POST /api/routes/plan response
 *   onError(error)    optional; the error is also shown inline
 *   style             container style
 */
export default function SearchHUD({ city = 'Bucharest', onSearchStart, onRoutePlanned, onError, style }) {
  const [prompt, setPrompt] = useState('');
  const [preset, setPreset] = useState('green_shady');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const mounted = useRef(true);
  const inFlight = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const activePreset = VIBE_PRESETS.find((p) => p.id === preset);
  const trimmed = prompt.trim();
  const canSubmit = trimmed.length >= MIN_PROMPT && !loading;

  const togglePreset = useCallback((id) => {
    setPreset((current) => (current === id ? null : id));
  }, []);

  const submit = useCallback(async () => {
    if (inFlight.current) return;
    if (trimmed.length < MIN_PROMPT) {
      setError('Tell me where you want to go, e.g. "UPB Regie to Carol Park".');
      return;
    }
    inFlight.current = true;
    Keyboard.dismiss();
    setError(null);
    setLoading(true);
    if (onSearchStart) onSearchStart();
    try {
      const data = await planRoute({
        user_prompt: trimmed.slice(0, MAX_PROMPT),
        vibe_preset: preset || 'green_shady',
        city,
      });
      if (!data || !data.plan || !data.geojson) {
        throw new Error('The route planner returned an unexpected answer. Please try again.');
      }
      if (onRoutePlanned) onRoutePlanned(data, { prompt: trimmed, vibePreset: preset });
    } catch (err) {
      if (mounted.current) setError(err.message || 'Something went wrong while planning your route.');
      if (onError) onError(err);
    } finally {
      inFlight.current = false;
      if (mounted.current) setLoading(false);
    }
  }, [trimmed, preset, city, onSearchStart, onRoutePlanned, onError]);

  return (
    <View style={[styles.container, style]}>
      <View style={styles.inputRow}>
        <TextInput
          style={styles.input}
          value={prompt}
          onChangeText={(text) => {
            setPrompt(text);
            if (error) setError(null);
          }}
          placeholder={activePreset ? activePreset.placeholder : 'Where to? Describe the vibe you want'}
          placeholderTextColor={colors.muted}
          multiline
          maxLength={MAX_PROMPT}
          returnKeyType="go"
          blurOnSubmit
          onSubmitEditing={submit}
          editable={!loading}
          accessibilityLabel="Describe your ride"
        />
        <TouchableOpacity
          style={[styles.goButton, !canSubmit && styles.goButtonDisabled]}
          onPress={submit}
          disabled={!canSubmit}
          accessibilityRole="button"
          accessibilityLabel="Find a calm route"
        >
          {loading ? <ActivityIndicator color="#fff" /> : <Text style={styles.goText}>Go</Text>}
        </TouchableOpacity>
      </View>

      <View style={styles.chips}>
        {VIBE_PRESETS.map((p) => {
          const selected = p.id === preset;
          return (
            <TouchableOpacity
              key={p.id}
              style={[styles.chip, selected && styles.chipSelected]}
              onPress={() => togglePreset(p.id)}
              disabled={loading}
              accessibilityRole="button"
              accessibilityState={{ selected }}
            >
              <Text style={[styles.chipText, selected && styles.chipTextSelected]}>
                {p.emoji} {p.label}
              </Text>
            </TouchableOpacity>
          );
        })}
      </View>

      {loading ? <Text style={styles.status}>Finding the calmest way…</Text> : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    padding: 12,
    borderWidth: 1,
    borderColor: colors.border,
    shadowColor: '#000',
    shadowOpacity: 0.25,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
    elevation: 6,
  },
  inputRow: { flexDirection: 'row', alignItems: 'center' },
  input: {
    flex: 1,
    minHeight: 44,
    maxHeight: 96,
    color: colors.text,
    fontSize: 16,
    paddingHorizontal: 12,
    paddingVertical: 10,
    backgroundColor: colors.cardAlt,
    borderRadius: radius.md,
  },
  goButton: {
    marginLeft: 10,
    minWidth: 56,
    height: 44,
    borderRadius: radius.md,
    backgroundColor: colors.accent,
    alignItems: 'center',
    justifyContent: 'center',
  },
  goButtonDisabled: { opacity: 0.45 },
  goText: { color: '#fff', fontWeight: '700', fontSize: 16 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', marginTop: 10 },
  chip: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.cardAlt,
    marginRight: 8,
    marginBottom: 6,
  },
  chipSelected: { backgroundColor: colors.calm, borderColor: colors.calm },
  chipText: { color: colors.text, fontSize: 13, fontWeight: '600' },
  chipTextSelected: { color: '#06231a' },
  status: { color: colors.muted, marginTop: 6, fontSize: 13 },
  error: { color: colors.danger, marginTop: 6, fontSize: 13 },
});

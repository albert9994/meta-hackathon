import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  KeyboardAvoidingView,
  Modal,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import { finishRide, postToFeed } from '../utils/api';
import { colors, radius } from '../utils/theme';

/**
 * Post-ride summary: stats, AI recap, dynamic badge, trivia quiz and feed sharing.
 *
 * Props
 *   visible    boolean
 *   ride       { user_name, crew_code?, route_title, distance_km, duration_min, vibe_preset }
 *              (exactly the POST /api/ride/finish request body)
 *   onClose()  required
 *   onFinished(result)   optional, called once with the /api/ride/finish response
 *   onPosted(postId)     optional, called after a successful feed post
 *
 * Privacy: only the aggregate distance is logged server-side; the route path is never sent.
 */
export default function EndRideModal({ visible, ride, onClose, onFinished, onPosted }) {
  const [phase, setPhase] = useState('loading'); // loading | done | error
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [pickedIndex, setPickedIndex] = useState(null);

  const [caption, setCaption] = useState('');
  const [photo, setPhoto] = useState(null); // { uri, base64 }
  const [posting, setPosting] = useState(false);
  const [posted, setPosted] = useState(false);
  const [postError, setPostError] = useState(null);

  const mounted = useRef(true);
  const requestedFor = useRef(null); // the ride object we already submitted (prevents double-logging)

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const submitRide = useCallback(async (rideToSend) => {
    setPhase('loading');
    setError(null);
    try {
      const data = await finishRide(rideToSend);
      if (!data || !data.stats || !data.quiz || !data.badge) {
        throw new Error('The ride summary came back incomplete. Please try again.');
      }
      if (!mounted.current) return;
      setResult(data);
      setPhase('done');
      if (onFinished) {
        try {
          onFinished(data);
        } catch (_) {
          /* a faulty callback must not break the summary */
        }
      }
    } catch (err) {
      if (!mounted.current) return;
      setError(err.message || 'Could not finish the ride.');
      setPhase('error');
    }
  }, [onFinished]);

  // Submit once per ride; reset everything when the modal closes.
  useEffect(() => {
    if (!visible) {
      requestedFor.current = null;
      setResult(null);
      setError(null);
      setPickedIndex(null);
      setCaption('');
      setPhoto(null);
      setPosting(false);
      setPosted(false);
      setPostError(null);
      return;
    }
    // Keyed by content, so a parent re-rendering with a fresh-but-identical object never re-submits.
    const rideKey = ride ? JSON.stringify(ride) : null;
    if (ride && requestedFor.current !== rideKey) {
      requestedFor.current = rideKey;
      submitRide(ride);
    }
  }, [visible, ride, submitRide]);

  const pickPhoto = useCallback(async (source) => {
    setPostError(null);
    try {
      const permission =
        source === 'camera'
          ? await ImagePicker.requestCameraPermissionsAsync()
          : await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!permission.granted) {
        setPostError(source === 'camera' ? 'Camera permission was denied.' : 'Photo library permission was denied.');
        return;
      }
      const options = { quality: 0.4, base64: true, exif: false };
      const picked =
        source === 'camera' ? await ImagePicker.launchCameraAsync(options) : await ImagePicker.launchImageLibraryAsync(options);
      if (picked.canceled) return;
      const asset = picked.assets && picked.assets[0];
      if (!asset || !asset.base64) {
        setPostError('That photo could not be read. Try another one.');
        return;
      }
      if (mounted.current) setPhoto({ uri: asset.uri, base64: asset.base64 });
    } catch (err) {
      if (mounted.current) setPostError(err.message || 'Could not get the photo.');
    }
  }, []);

  const sharePost = useCallback(async () => {
    if (!ride || !result || posting || posted) return;
    if (!photo && !caption.trim()) {
      setPostError('Add a photo or a caption first.');
      return;
    }
    setPosting(true);
    setPostError(null);
    try {
      const body = {
        user_name: ride.user_name,
        caption: caption.trim(),
        badge_title: result.badge.title,
        stats: result.stats,
      };
      if (photo) body.image_base64 = photo.base64;
      if (ride.crew_code) body.crew_code = ride.crew_code;
      const response = await postToFeed(body);
      if (!mounted.current) return;
      setPosted(true);
      if (onPosted) onPosted(response && response.id);
    } catch (err) {
      if (mounted.current) setPostError(err.message || 'Could not share your ride.');
    } finally {
      if (mounted.current) setPosting(false);
    }
  }, [ride, result, photo, caption, posting, posted, onPosted]);

  const quiz = result && result.quiz;
  const answered = pickedIndex !== null;
  const gotItRight = answered && quiz && pickedIndex === quiz.correct_index;

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView style={styles.screen} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <Text style={styles.kicker}>Ride complete</Text>
          <Text style={styles.routeTitle}>{ride ? ride.route_title : ''}</Text>

          {phase === 'loading' ? (
            <View style={styles.center}>
              <ActivityIndicator size="large" color={colors.accent} />
              <Text style={styles.muted}>Writing up your calm ride…</Text>
            </View>
          ) : null}

          {phase === 'error' ? (
            <View style={styles.card}>
              <Text style={styles.errorText}>{error}</Text>
              <TouchableOpacity style={styles.primary} onPress={() => ride && submitRide(ride)} accessibilityRole="button">
                <Text style={styles.primaryText}>Try again</Text>
              </TouchableOpacity>
            </View>
          ) : null}

          {phase === 'done' && result ? (
            <>
              <View style={styles.statsCard}>
                <Text style={styles.bigNumber}>{result.stats.distance_km}</Text>
                <Text style={styles.bigLabel}>mindful km · traffic avoided</Text>
                <View style={styles.statsRow}>
                  <Stat label="Time" value={`${result.stats.duration_min} min`} />
                  <Stat label="Avg speed" value={`${result.stats.avg_speed_kmh} km/h`} />
                </View>
              </View>

              <Text style={styles.recap}>{result.recap_text}</Text>

              <View style={styles.badgeCard}>
                <Text style={styles.badgeTitle}>{result.badge.title}</Text>
                {result.badge.lore ? <Text style={styles.badgeLore}>{result.badge.lore}</Text> : null}
              </View>

              <View style={styles.card}>
                <Text style={styles.sectionTitle}>Quick quiz</Text>
                <Text style={styles.question}>{quiz.question}</Text>
                {quiz.options.map((option, index) => {
                  const isCorrect = index === quiz.correct_index;
                  const isPicked = index === pickedIndex;
                  return (
                    <TouchableOpacity
                      key={`${index}-${option}`}
                      style={[
                        styles.option,
                        answered && isCorrect && styles.optionCorrect,
                        answered && isPicked && !isCorrect && styles.optionWrong,
                      ]}
                      onPress={() => !answered && setPickedIndex(index)}
                      disabled={answered}
                      accessibilityRole="button"
                    >
                      <Text style={styles.optionText}>{option}</Text>
                    </TouchableOpacity>
                  );
                })}
                {answered ? (
                  <View style={{ marginTop: 8 }}>
                    <Text style={[styles.verdict, { color: gotItRight ? colors.calm : colors.warn }]}>
                      {gotItRight ? 'Spot on! 🎉' : 'Not quite!'}
                    </Text>
                    {quiz.fun_fact ? <Text style={styles.muted}>{quiz.fun_fact}</Text> : null}
                  </View>
                ) : null}
              </View>

              <View style={styles.card}>
                <Text style={styles.sectionTitle}>Share your ride</Text>
                {posted ? (
                  <Text style={styles.success}>Shared! 🌿 Your calm ride is on the feed.</Text>
                ) : (
                  <>
                    <TextInput
                      style={styles.input}
                      value={caption}
                      onChangeText={setCaption}
                      placeholder="Add a caption (optional)"
                      placeholderTextColor={colors.muted}
                      maxLength={280}
                      multiline
                      editable={!posting}
                    />
                    {photo ? <Image source={{ uri: photo.uri }} style={styles.photo} resizeMode="cover" /> : null}
                    <View style={styles.photoButtons}>
                      <TouchableOpacity style={styles.secondary} onPress={() => pickPhoto('camera')} disabled={posting}>
                        <Text style={styles.secondaryText}>📷 Camera</Text>
                      </TouchableOpacity>
                      <TouchableOpacity style={styles.secondary} onPress={() => pickPhoto('library')} disabled={posting}>
                        <Text style={styles.secondaryText}>🖼️ Library</Text>
                      </TouchableOpacity>
                    </View>
                    <Text style={styles.muted}>
                      {ride && ride.crew_code ? `Visible to your crew (${ride.crew_code}) only.` : 'Visible to everyone on the community feed.'}
                    </Text>
                    {postError ? <Text style={styles.errorText}>{postError}</Text> : null}
                    <TouchableOpacity
                      style={[styles.primary, posting && styles.disabled]}
                      onPress={sharePost}
                      disabled={posting}
                      accessibilityRole="button"
                    >
                      {posting ? <ActivityIndicator color="#fff" /> : <Text style={styles.primaryText}>Post to feed</Text>}
                    </TouchableOpacity>
                  </>
                )}
              </View>
            </>
          ) : null}

          <TouchableOpacity style={styles.closeButton} onPress={onClose} accessibilityRole="button">
            <Text style={styles.closeText}>{phase === 'done' ? 'Done' : 'Close'}</Text>
          </TouchableOpacity>
        </ScrollView>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function Stat({ label, value }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20, paddingTop: 56, paddingBottom: 40 },
  kicker: { color: colors.calm, fontSize: 13, fontWeight: '800', letterSpacing: 1.2, textTransform: 'uppercase' },
  routeTitle: { color: colors.text, fontSize: 24, fontWeight: '800', marginTop: 4, marginBottom: 16 },
  center: { alignItems: 'center', paddingVertical: 48 },
  muted: { color: colors.muted, fontSize: 13, lineHeight: 18, marginTop: 6 },
  statsCard: { backgroundColor: colors.card, borderRadius: radius.lg, padding: 20, alignItems: 'center', marginBottom: 16 },
  bigNumber: { color: colors.text, fontSize: 56, fontWeight: '900' },
  bigLabel: { color: colors.muted, fontSize: 14, marginTop: -4 },
  statsRow: { flexDirection: 'row', marginTop: 16, alignSelf: 'stretch' },
  stat: { flex: 1, alignItems: 'center' },
  statValue: { color: colors.text, fontSize: 18, fontWeight: '700' },
  statLabel: { color: colors.muted, fontSize: 12, marginTop: 2 },
  recap: { color: colors.text, fontSize: 16, lineHeight: 24, marginBottom: 16 },
  badgeCard: { backgroundColor: colors.cardAlt, borderRadius: radius.lg, padding: 18, borderWidth: 1, borderColor: colors.accent, marginBottom: 16 },
  badgeTitle: { color: colors.text, fontSize: 22, fontWeight: '900' },
  badgeLore: { color: colors.muted, fontSize: 14, lineHeight: 20, marginTop: 6 },
  card: { backgroundColor: colors.card, borderRadius: radius.lg, padding: 16, marginBottom: 16 },
  sectionTitle: { color: colors.calm, fontSize: 13, fontWeight: '800', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 },
  question: { color: colors.text, fontSize: 16, fontWeight: '700', lineHeight: 22, marginBottom: 10 },
  option: { backgroundColor: colors.cardAlt, borderRadius: radius.md, padding: 14, marginBottom: 8, borderWidth: 1, borderColor: colors.border },
  optionCorrect: { borderColor: colors.calm, backgroundColor: '#1d4a37' },
  optionWrong: { borderColor: colors.danger, backgroundColor: '#4a2323' },
  optionText: { color: colors.text, fontSize: 15 },
  verdict: { fontSize: 16, fontWeight: '800', marginBottom: 2 },
  input: { backgroundColor: colors.cardAlt, color: colors.text, borderRadius: radius.md, padding: 12, minHeight: 48, fontSize: 15, marginBottom: 10 },
  photo: { width: '100%', height: 180, borderRadius: radius.md, marginBottom: 10 },
  photoButtons: { flexDirection: 'row', marginBottom: 4 },
  secondary: { flex: 1, backgroundColor: colors.cardAlt, borderRadius: radius.md, paddingVertical: 12, alignItems: 'center', marginRight: 8, borderWidth: 1, borderColor: colors.border },
  secondaryText: { color: colors.text, fontWeight: '700' },
  primary: { backgroundColor: colors.accent, borderRadius: radius.md, paddingVertical: 14, alignItems: 'center', marginTop: 12 },
  primaryText: { color: '#fff', fontSize: 16, fontWeight: '800' },
  disabled: { opacity: 0.5 },
  errorText: { color: colors.danger, fontSize: 14, marginTop: 8, lineHeight: 20 },
  success: { color: colors.calm, fontSize: 15, fontWeight: '700' },
  closeButton: { alignItems: 'center', paddingVertical: 14, marginTop: 4 },
  closeText: { color: colors.muted, fontSize: 16, fontWeight: '700' },
});
